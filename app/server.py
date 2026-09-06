from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    from .date_chat import ChatService, DemoProvider, LMStudioProvider, SessionStore, read_json
    from .profiles import (
        BUILTIN_SCENARIOS,
        CHARACTER_RESPONSE_FORMAT,
        SCENARIO_RESPONSE_FORMAT,
        JsonProfileStore,
        character_generation_messages,
        normalize_character,
        normalize_scenario,
        scenario_generation_messages,
    )
    from .video_generation import DEFAULT_BASE_URL, FastH3VideoGenerator
except ImportError:  # Support direct execution: python app/server.py
    from date_chat import ChatService, DemoProvider, LMStudioProvider, SessionStore, read_json
    from profiles import (
        BUILTIN_SCENARIOS,
        CHARACTER_RESPONSE_FORMAT,
        SCENARIO_RESPONSE_FORMAT,
        JsonProfileStore,
        character_generation_messages,
        normalize_character,
        normalize_scenario,
        scenario_generation_messages,
    )
    from video_generation import DEFAULT_BASE_URL, FastH3VideoGenerator


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = PROJECT_ROOT / "app" / "static"
MEDIA_ROOT = PROJECT_ROOT / "media"
DATA_ROOT = Path(os.environ.get("DATE_CHAT_DATA_ROOT", str(PROJECT_ROOT / "data"))).expanduser().resolve()
SESSIONS_ROOT = DATA_ROOT / "sessions"
CHARACTERS_ROOT = DATA_ROOT / "characters"
SCENARIOS_ROOT = DATA_ROOT / "scenarios"
REFERENCE_IMAGES_ROOT = DATA_ROOT / "reference_images"
WORK_ROOT = Path(os.environ.get("DATE_CHAT_WORK_ROOT", str(PROJECT_ROOT / "work"))).expanduser().resolve()
DEFAULT_CHARACTER_PATH = PROJECT_ROOT / "config" / "character.example.json"
DEFAULT_OPENING_PATH = MEDIA_ROOT / "opening.mp4"
DEFAULT_REFERENCE_PATH = MEDIA_ROOT / "default-character-reference.png"
DEFAULT_LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
MAX_REFERENCE_IMAGE_BYTES = 12 * 1024 * 1024
REFERENCE_IMAGE_EXTENSIONS = (".png", ".jpg", ".webp")


def clean_url(value: Any, default: str) -> str:
    text = str(value or default).strip().rstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("接続先は http または https のURLで指定してください")
    return text[:500]


def normalize_runtime(raw: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    provider_raw = raw.get("provider") if isinstance(raw.get("provider"), dict) else {}
    provider_type = str(provider_raw.get("type") or defaults["provider"]["type"])
    if provider_type not in {"demo", "lmstudio"}:
        raise ValueError("会話モードが正しくありません")
    model_value = provider_raw.get("model")
    model = str(model_value).strip()[:300] if isinstance(model_value, str) and model_value.strip() else None
    provider = {
        "type": provider_type,
        "base_url": clean_url(provider_raw.get("base_url"), defaults["provider"]["base_url"]),
        "model": model,
    }

    video_raw = raw.get("video") if isinstance(raw.get("video"), dict) else {}
    video_mode = str(video_raw.get("mode") or defaults["video"]["mode"])
    if video_mode not in {"none", "fasth3"}:
        raise ValueError("映像モードが正しくありません")
    reference_mode = str(video_raw.get("reference_mode") or defaults["video"].get("reference_mode") or "omni")
    if reference_mode not in {"omni", "first_frame"}:
        raise ValueError("参照方式が正しくありません")
    reference_image_id = video_raw.get("reference_image_id")
    if reference_image_id in {None, ""}:
        reference_image_id = None
    elif not isinstance(reference_image_id, str) or (
        reference_image_id != "default" and not re.fullmatch(r"[0-9a-f]{32}", reference_image_id)
    ):
        raise ValueError("参照画像IDが正しくありません")
    ref_image_size = str(video_raw.get("ref_image_size") or defaults["video"].get("ref_image_size") or "match")
    if ref_image_size not in {"match", "max"}:
        raise ValueError("参照画像サイズ設定が正しくありません")
    video = {
        "mode": video_mode,
        "base_url": clean_url(video_raw.get("base_url"), defaults["video"]["base_url"]),
        "reference_mode": reference_mode,
        "reference_image_id": reference_image_id,
        "ref_image_size": ref_image_size,
    }
    return {"provider": provider, "video": video}


def reference_image_path(reference_id: str) -> Path:
    if reference_id == "default":
        if DEFAULT_REFERENCE_PATH.is_file():
            return DEFAULT_REFERENCE_PATH
        raise FileNotFoundError(reference_id)
    if not re.fullmatch(r"[0-9a-f]{32}", str(reference_id or "")):
        raise ValueError("参照画像IDが正しくありません")
    for extension in REFERENCE_IMAGE_EXTENSIONS:
        candidate = REFERENCE_IMAGES_ROOT / f"{reference_id}{extension}"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(reference_id)


def reference_image_extension(content: bytes) -> str:
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("参照画像はPNG、JPEG、WebPのいずれかを選んでください")


def provider_from_runtime(runtime: dict[str, Any]) -> DemoProvider | LMStudioProvider:
    config = runtime["provider"]
    if config["type"] == "demo":
        return DemoProvider()
    return LMStudioProvider(
        base_url=config["base_url"],
        model=config.get("model"),
        timeout_seconds=float(os.environ.get("LM_STUDIO_TIMEOUT", "60")),
    )


class DateChatHTTPServer(ThreadingHTTPServer):
    service: ChatService
    defaults: dict[str, Any]
    character_store: JsonProfileStore
    scenario_store: JsonProfileStore
    opening_path: Path


class Handler(BaseHTTPRequestHandler):
    server_version = "FastH3DateChat/2.0"

    @property
    def service(self) -> ChatService:
        return self.server.service  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        sys.stdout.write("[%s] %s\n" % (self.log_date_time_string(), format % args))

    def _send_json(self, value: Any, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > 65_536:
            raise ValueError("Request body must be between 1 and 65536 bytes")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Request body must be valid UTF-8 JSON") from exc
        if not isinstance(value, dict):
            raise ValueError("Request JSON root must be an object")
        return value

    def _read_reference_image(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > MAX_REFERENCE_IMAGE_BYTES:
            raise ValueError("参照画像は12MB以下にしてください")
        return self.rfile.read(length)

    def _serve_file(self, root: Path, relative: str) -> None:
        candidate = (root / unquote(relative)).resolve()
        try:
            candidate.relative_to(root.resolve())
        except ValueError:
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        content = candidate.read_bytes()
        mime, _ = mimetypes.guess_type(candidate.name)
        content_type = mime or "application/octet-stream"
        if content_type.startswith("text/") or content_type in {
            "application/javascript", "application/json", "image/svg+xml",
        }:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _settings_payload(self) -> dict[str, Any]:
        default_character = {"id": "default", **normalize_character(self.service.character)}
        characters = [default_character]
        for item in self.server.character_store.list():  # type: ignore[attr-defined]
            try:
                characters.append({"id": item["id"], **normalize_character(item)})
            except (KeyError, ValueError, TypeError):
                continue
        scenarios = [{"builtin": True, **item} for item in BUILTIN_SCENARIOS]
        for item in self.server.scenario_store.list():  # type: ignore[attr-defined]
            try:
                scenarios.append({"id": item["id"], "builtin": False, **normalize_scenario(item)})
            except (KeyError, ValueError, TypeError):
                continue
        return {
            "defaults": self.server.defaults,  # type: ignore[attr-defined]
            "characters": characters,
            "scenarios": scenarios,
            "opening_video_available": self.server.opening_path.is_file(),  # type: ignore[attr-defined]
        }

    def _character(self, profile_id: Any) -> dict[str, Any]:
        if profile_id in {None, "", "default"}:
            return {"profile_id": "default", **normalize_character(self.service.character)}
        if not isinstance(profile_id, str):
            raise ValueError("キャラクターを選択してください")
        value = self.server.character_store.load(profile_id)  # type: ignore[attr-defined]
        return {"profile_id": profile_id, **normalize_character(value)}

    def _scenario(self, profile_id: Any) -> dict[str, Any]:
        selected = str(profile_id or "night_chat")
        for item in BUILTIN_SCENARIOS:
            if item["id"] == selected:
                return dict(item)
        value = self.server.scenario_store.load(selected)  # type: ignore[attr-defined]
        return {"id": selected, **normalize_scenario(value)}

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send_json({
                "ok": True,
                "app": "fasth3-date-chat",
                "character": {
                    "name": self.service.character.get("name"),
                    "tagline": self.service.character.get("tagline"),
                },
                "video": {
                    "url": "/media/opening.mp4" if self.server.opening_path.is_file() else None,  # type: ignore[attr-defined]
                    "width": 320,
                    "height": 320,
                },
            })
            return
        if path == "/api/settings":
            self._send_json(self._settings_payload())
            return
        if path.startswith("/api/reference-images/"):
            reference_id = path.removeprefix("/api/reference-images/")
            try:
                reference_path = reference_image_path(reference_id)
                self._serve_file(reference_path.parent, reference_path.name)
            except (FileNotFoundError, ValueError):
                self._send_json({"error": "reference image not found"}, HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/media/"):
            self._serve_file(MEDIA_ROOT, path.removeprefix("/media/"))
            return
        if path.startswith("/api/sessions/"):
            session_id = path.removeprefix("/api/sessions/")
            try:
                self._send_json(self.service.get_session(session_id))
            except (FileNotFoundError, ValueError):
                self._send_json({"error": "session not found"}, HTTPStatus.NOT_FOUND)
            return
        if path.startswith("/api/"):
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            return
        relative = "index.html" if path == "/" else path.lstrip("/")
        self._serve_file(STATIC_ROOT, relative)

    def _generate_profile(self, body: dict[str, Any], kind: str) -> dict[str, Any]:
        runtime = normalize_runtime(
            {"provider": {
                "type": "lmstudio",
                "base_url": body.get("base_url"),
                "model": body.get("model"),
            }},
            self.server.defaults,  # type: ignore[attr-defined]
        )
        provider = provider_from_runtime(runtime)
        if not isinstance(provider, LMStudioProvider):
            raise ValueError("設定作成にはLM Studioが必要です")
        description = body.get("description")
        if kind == "character":
            system, user = character_generation_messages(description)
            raw = provider.complete_json(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                CHARACTER_RESPONSE_FORMAT,
                max_tokens=1500,
            )
            return normalize_character(raw)
        system, user = scenario_generation_messages(description)
        raw = provider.complete_json(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            SCENARIO_RESPONSE_FORMAT,
            max_tokens=1500,
        )
        return normalize_scenario(raw)

    def _generate_scene(self, session: dict[str, Any], runtime: dict[str, Any]) -> None:
        message = session["messages"][-1]
        visual_moment = message["visual_moment"]
        config = runtime["video"]
        generator = FastH3VideoGenerator(MEDIA_ROOT, WORK_ROOT, base_url=config["base_url"])
        video = generator.generate(
            session_id=session["id"],
            message_id=message["id"],
            character=session["character"],
            dialogue=message["content"],
            moment=visual_moment.get("summary") or session.get("scenario", {}).get("visual_context"),
            reference_path=reference_image_path(config["reference_image_id"]),
            reference_mode=config["reference_mode"],
            ref_image_size=config["ref_image_size"],
        )
        visual_moment.update(video)
        visual_moment["requested"] = True

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            if path == "/api/reference-images":
                content = self._read_reference_image()
                extension = reference_image_extension(content)
                reference_id = uuid.uuid4().hex
                REFERENCE_IMAGES_ROOT.mkdir(parents=True, exist_ok=True)
                output = REFERENCE_IMAGES_ROOT / f"{reference_id}{extension}"
                temporary = output.with_suffix(extension + ".tmp")
                temporary.write_bytes(content)
                os.replace(temporary, output)
                self._send_json({
                    "id": reference_id,
                    "url": f"/api/reference-images/{reference_id}",
                }, HTTPStatus.CREATED)
                return
            if path == "/api/sessions":
                body = self._read_json()
                runtime = normalize_runtime(body, self.server.defaults)  # type: ignore[attr-defined]
                if runtime["video"]["mode"] == "fasth3":
                    reference_id = runtime["video"].get("reference_image_id")
                    if not reference_id:
                        raise ValueError("FastH3を使うにはキャラクターの参照画像を選んでください")
                    reference_image_path(reference_id)
                character = self._character(body.get("character_id"))
                scenario = self._scenario(body.get("scenario_id"))
                session = self.service.new_session(character, scenario, runtime)
                session["opening_video_url"] = (
                    "/media/opening.mp4"
                    if (runtime["video"]["mode"] != "fasth3"
                        or runtime["video"]["reference_image_id"] == "default")
                    and character.get("profile_id") == "default"
                    and scenario.get("id") == "night_chat"
                    and self.server.opening_path.is_file()  # type: ignore[attr-defined]
                    else None
                )
                if session["opening_video_url"] is None and runtime["video"]["mode"] == "fasth3":
                    self._generate_scene(session, runtime)
                    session["opening_video_url"] = session["messages"][-1]["visual_moment"]["video_url"]
                self.service.save_session(session)
                self._send_json(session, HTTPStatus.CREATED)
                return
            if path == "/api/connections/test":
                body = self._read_json()
                kind = body.get("kind")
                if kind == "lmstudio":
                    runtime = normalize_runtime({"provider": {
                        "type": "lmstudio", "base_url": body.get("base_url"), "model": body.get("model"),
                    }}, self.server.defaults)  # type: ignore[attr-defined]
                    status = provider_from_runtime(runtime).status()
                elif kind == "fasth3":
                    url = clean_url(body.get("base_url"), self.server.defaults["video"]["base_url"])  # type: ignore[attr-defined]
                    reference_mode = str(body.get("reference_mode") or "omni")
                    status = FastH3VideoGenerator(MEDIA_ROOT, WORK_ROOT, base_url=url).status(reference_mode)
                else:
                    raise ValueError("確認する接続先を選んでください")
                self._send_json(status, HTTPStatus.OK if status.get("ok") else HTTPStatus.BAD_GATEWAY)
                return
            if path == "/api/characters/generate":
                self._send_json({"profile": self._generate_profile(self._read_json(), "character")})
                return
            if path == "/api/characters":
                profile = normalize_character(self._read_json().get("profile"))
                self._send_json(self.server.character_store.save(profile), HTTPStatus.CREATED)  # type: ignore[attr-defined]
                return
            if path == "/api/scenarios/generate":
                self._send_json({"profile": self._generate_profile(self._read_json(), "scenario")})
                return
            if path == "/api/scenarios":
                profile = normalize_scenario(self._read_json().get("profile"))
                self._send_json(self.server.scenario_store.save(profile), HTTPStatus.CREATED)  # type: ignore[attr-defined]
                return
            if path == "/api/chat":
                body = self._read_json()
                session_id = body.get("session_id")
                if not isinstance(session_id, str):
                    raise ValueError("session_id must be a string")
                existing = self.service.get_session(session_id)
                runtime = normalize_runtime(existing.get("runtime") or {}, self.server.defaults)  # type: ignore[attr-defined]
                provider = provider_from_runtime(runtime)
                session = self.service.prepare_send(session_id, body.get("message"), provider=provider)
                assistant_message = session["messages"][-1]
                visual_moment = assistant_message["visual_moment"]
                if runtime["video"]["mode"] == "fasth3":
                    self._generate_scene(session, runtime)
                else:
                    visual_moment.update({
                        "requested": False,
                        "video_url": None,
                        "dialogue": assistant_message["content"],
                    })
                self.service.save_session(session)
                self._send_json(session)
                return
            self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
        except FileNotFoundError:
            self._send_json({"error": "選択した設定が見つかりません"}, HTTPStatus.NOT_FOUND)
        except (TypeError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except RuntimeError as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_GATEWAY)


def create_service(provider_name: str, character_path: Path) -> ChatService:
    character = normalize_character(read_json(character_path))
    store = SessionStore(SESSIONS_ROOT)
    if provider_name == "demo":
        provider = DemoProvider()
    else:
        provider = LMStudioProvider(
            base_url=os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_LM_STUDIO_URL),
            model=os.environ.get("LM_STUDIO_MODEL") or None,
            timeout_seconds=float(os.environ.get("LM_STUDIO_TIMEOUT", "60")),
        )
    return ChatService(store, provider, character)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local FastH3 conversation game server")
    parser.add_argument("--host", default=os.environ.get("APP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("APP_PORT", "8767")))
    parser.add_argument("--provider", choices=("lmstudio", "demo"), default=os.environ.get("CHAT_PROVIDER", "demo"))
    parser.add_argument("--video-mode", choices=("none", "fasth3"), default=os.environ.get("VIDEO_MODE", "none"))
    parser.add_argument(
        "--character",
        type=Path,
        default=Path(os.environ.get("CHARACTER_CONFIG", str(DEFAULT_CHARACTER_PATH))),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    character_path = args.character.expanduser().resolve()
    if not character_path.is_file():
        raise SystemExit(f"Character configuration not found: {character_path}")
    defaults = {
        "provider": {
            "type": args.provider,
            "base_url": os.environ.get("LM_STUDIO_BASE_URL", DEFAULT_LM_STUDIO_URL),
            "model": os.environ.get("LM_STUDIO_MODEL") or None,
        },
        "video": {
            "mode": args.video_mode,
            "base_url": os.environ.get("FASTH3_BASE_URL", DEFAULT_BASE_URL),
            "reference_mode": os.environ.get("FASTH3_REFERENCE_MODE", "omni"),
            "reference_image_id": "default" if DEFAULT_REFERENCE_PATH.is_file() else None,
            "ref_image_size": os.environ.get("FASTH3_REF_IMAGE_SIZE", "match"),
        },
        "character_id": "default",
        "scenario_id": "night_chat",
    }
    server = DateChatHTTPServer((args.host, args.port), Handler)
    server.service = create_service(args.provider, character_path)
    server.defaults = defaults
    server.character_store = JsonProfileStore(CHARACTERS_ROOT, "character")
    server.scenario_store = JsonProfileStore(SCENARIOS_ROOT, "scenario")
    server.opening_path = DEFAULT_OPENING_PATH
    print(f"FastH3 Date Chat: http://{args.host}:{args.port}")
    print("The browser settings screen selects chat, video, character, and scenario per session.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
