from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "http://127.0.0.1:8002"
MODEL = os.environ.get(
    "FASTH3_MODEL",
    "minimax_h3_fastvideo_vsa_datafree_1300step_4step_int8_convrot.safetensors",
)
CLIP = os.environ.get(
    "FASTH3_TEXT_ENCODER",
    "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
)
VIDEO_VAE = os.environ.get("FASTH3_VIDEO_VAE", "minimax_h3_video_vae_fp16.safetensors")
AUDIO_VAE = os.environ.get("FASTH3_AUDIO_VAE", "minimax_h3_audio_vae_fp32.safetensors")
USE_SOL_ATTN = os.environ.get("FASTH3_USE_SOL_ATTN", "1").strip().lower() not in {"0", "false", "no"}
WIDTH = 320
HEIGHT = 320
FRAMES = 72
FPS = 24.0
DEFAULT_CHARACTER_SEED = 986429173


def build_video_prompt(character: dict[str, Any], dialogue: str, moment: str | None) -> str:
    name = str(character.get("name") or "Mio")
    anchor = str(
        character.get("visual_prompt")
        or character.get("visual_anchor")
        or "Photorealistic live-action footage of the same young adult Japanese woman in a warmly lit room at night."
    )
    scene = str(moment or "こちらを見て短く自然に返事をする")
    exact_dialogue = json.dumps(dialogue.strip(), ensure_ascii=False)
    return f"""A cinematic Japanese visual novel scene, medium close-up, square 1:1 composition.
Character name: {name}.
IMMUTABLE CHARACTER AND STYLE BLOCK — preserve every detail exactly in every generated turn:
{anchor}
The next line may change only her facial expression, gaze, or a small natural gesture. It must not change identity, facial features, hairstyle, glasses, clothing, location, lighting, color grade, or visual style.
Current expression or small gesture: {scene}.
One continuous three-second shot, stable face and clothing, subtle realistic motion, no camera cut,
no on-screen text, no captions, no subtitles.
She speaks only Japanese. She says exactly the following Japanese dialogue and says nothing else:
{exact_dialogue}
Natural calm Japanese female voice, intimate conversational delivery. No English speech."""


def build_workflow(prompt: str, seed: int, filename_prefix: str) -> dict[str, Any]:
    model_source = ["19", 0] if USE_SOL_ATTN else ["17", 0]
    workflow = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": MODEL, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
        "5": {"class_type": "MiniMaxH3ImageToVideo", "inputs": {
            "clip": ["2", 0], "vae": ["3", 0], "prompt": prompt,
            "width": WIDTH, "height": HEIGHT, "length": FRAMES,
        }},
        "6": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "7": {"class_type": "BasicGuider", "inputs": {"model": model_source, "conditioning": ["5", 0]}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "BasicScheduler", "inputs": {
            "model": model_source, "scheduler": "normal", "steps": 4, "denoise": 1.0,
        }},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["6", 0], "guider": ["7", 0], "sampler": ["8", 0],
            "sigmas": ["9", 0], "latent_image": ["5", 1],
        }},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["10", 0], "vae": ["4", 0]}},
        "13": {"class_type": "CreateVideo", "inputs": {
            "images": ["11", 0], "audio": ["12", 0], "fps": FPS, "bit_depth": 8,
        }},
        "14": {"class_type": "SaveVideo", "inputs": {
            "video": ["13", 0], "filename_prefix": filename_prefix,
            "format": "mp4", "codec": "auto",
        }},
        "17": {"class_type": "MiniMaxH3SigmaShift", "inputs": {
            "model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0,
        }},
    }
    if USE_SOL_ATTN:
        workflow["19"] = {"class_type": "SolAttnMiniMax", "inputs": {
            "model": ["17", 0], "selection": "VSA (FastVideo)",
            "selection.vsa_keep_percent": 10.0, "start_percent": 0.0, "end_percent": 1.0,
            "min_tokens": 12288, "sink_conditioning": "exact_kv_and_rows", "verbose": False,
        }}
    return workflow


class FastH3VideoGenerator:
    def __init__(self, media_root: Path, work_root: Path, base_url: str | None = None):
        self.media_root = media_root
        self.work_root = work_root
        self.base_url = (base_url or os.environ.get("FASTH3_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request_json(self, method: str, path: str, payload: object | None = None, timeout: int = 90) -> Any:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"} if data is not None else {},
        )
        with self.opener.open(request, timeout=timeout) as response:
            return json.load(response)

    def assert_ready(self) -> None:
        queue = self._request_json("GET", "/queue", timeout=15)
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise RuntimeError("FastH3は別の生成中です。このターンはまだ送信されていません")
        unets = self._request_json("GET", "/object_info/UNETLoader", timeout=15)
        if MODEL not in json.dumps(unets, ensure_ascii=False):
            raise RuntimeError("FastH3の4-stepモデルが見つかりません。このターンはまだ送信されていません")

    def status(self) -> dict[str, Any]:
        """Return a read-only readiness summary without submitting a job."""
        try:
            self.assert_ready()
            return {"ok": True, "backend": "fasth3", "base_url": self.base_url}
        except Exception as exc:  # Health checks must not stop the web UI.
            return {"ok": False, "backend": "fasth3", "error": str(exc)}

    @staticmethod
    def _validated_id(value: str, field: str) -> str:
        if not re.fullmatch(r"[0-9a-f]{32}", value):
            raise ValueError(f"invalid {field}")
        return value

    @staticmethod
    def _find_video(entry: dict[str, Any]) -> dict[str, Any]:
        for output in entry.get("outputs", {}).values():
            for key in ("videos", "images"):
                for item in output.get(key, []):
                    if str(item.get("filename", "")).lower().endswith(".mp4"):
                        return item
        raise RuntimeError("FastH3は完了しましたがMP4が見つかりません")

    def _download(self, item: dict[str, Any], output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        query = urllib.parse.urlencode({
            "filename": item["filename"],
            "subfolder": item.get("subfolder", ""),
            "type": item.get("type", "output"),
        })
        partial = output.with_suffix(".mp4.part")
        with self.opener.open(self.base_url + "/view?" + query, timeout=600) as response, partial.open("wb") as handle:
            while block := response.read(1024 * 1024):
                handle.write(block)
        os.replace(partial, output)

    def _write_log(self, message_id: str, value: dict[str, Any]) -> None:
        directory = self.work_root / "video_jobs"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{message_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def generate(
        self,
        session_id: str,
        message_id: str,
        character: dict[str, Any],
        dialogue: str,
        moment: str | None,
    ) -> dict[str, Any]:
        session_id = self._validated_id(session_id, "session id")
        message_id = self._validated_id(message_id, "message id")
        self.assert_ready()
        started = time.time()
        seed = int(character.get("generation_seed", DEFAULT_CHARACTER_SEED))
        if not 0 <= seed < 2**63:
            raise ValueError("generation_seed must be between 0 and 2^63 - 1")
        prompt = build_video_prompt(character, dialogue, moment)
        filename_prefix = f"video/minimax-h3/fasth3-date-chat/{session_id[:8]}-{message_id[:8]}"
        workflow = build_workflow(prompt, seed, filename_prefix)
        response = self._request_json(
            "POST", "/prompt", {"prompt": workflow, "client_id": str(uuid.uuid4())}, timeout=60
        )
        prompt_id = response.get("prompt_id")
        if response.get("error") or not prompt_id:
            raise RuntimeError("FastH3へ動画を投入できませんでした")
        self._write_log(message_id, {
            "state": "queued", "prompt_id": prompt_id, "started": started,
            "session_id": session_id, "message_id": message_id, "workflow": workflow,
        })

        deadline = time.time() + 5 * 60
        while time.time() < deadline:
            history = self._request_json("GET", "/history/" + urllib.parse.quote(prompt_id), timeout=60)
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("completed") or status.get("status_str") in {"success", "error"}:
                    if status.get("status_str") != "success":
                        self._write_log(message_id, {"state": "error", "prompt_id": prompt_id, "history": history})
                        raise RuntimeError("FastH3の動画生成に失敗しました")
                    relative = Path("turns") / session_id / f"{message_id}.mp4"
                    output = self.media_root / relative
                    self._download(self._find_video(entry), output)
                    elapsed = round(time.time() - started, 3)
                    result = {
                        "state": "finished", "prompt_id": prompt_id, "elapsed_seconds": elapsed,
                        "output": relative.as_posix(), "session_id": session_id, "message_id": message_id,
                        "workflow": workflow,
                    }
                    self._write_log(message_id, result)
                    return {
                        "video_url": "/media/" + relative.as_posix(),
                        "dialogue": dialogue,
                        "prompt_id": prompt_id,
                        "elapsed_seconds": elapsed,
                        "width": WIDTH,
                        "height": HEIGHT,
                    }
            time.sleep(2)
        raise RuntimeError("FastH3の動画生成が5分以内に完了しませんでした")
