from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


MAX_MESSAGE_CHARS = 2000
MAX_HISTORY_MESSAGES = 20
ALLOWED_DATE_STATES = {"none", "tentative", "accepted", "declined"}

TURN_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "date_chat_turn",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "reply": {"type": "string"},
                "suggestions": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 2,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "id": {"type": "string", "enum": ["a", "b"]},
                            "text": {"type": "string"},
                        },
                        "required": ["id", "text"],
                    },
                },
                "state_patch": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "shared_topics": {"type": "array", "items": {"type": "string"}},
                        "date": {
                            "type": "object",
                            "additionalProperties": False,
                            "properties": {
                                "status": {
                                    "type": "string",
                                    "enum": ["none", "tentative", "accepted", "declined"],
                                },
                                "activity": {"type": ["string", "null"]},
                                "time_hint": {"type": ["string", "null"]},
                            },
                            "required": ["status", "activity", "time_hint"],
                        },
                    },
                    "required": ["shared_topics", "date"],
                },
                "visual_moment": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "requested": {"type": "boolean"},
                        "summary": {"type": ["string", "null"]},
                    },
                    "required": ["requested", "summary"],
                },
                "goal_tracking": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "reached": {"type": "boolean"},
                        "progress": {"type": "string"},
                    },
                    "required": ["reached", "progress"],
                },
            },
            "required": ["reply", "suggestions", "state_patch", "visual_moment", "goal_tracking"],
        },
    },
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON object expected: {path}")
    return value


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    if fenced:
        cleaned = fenced.group(1)

    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("LM Studio response did not contain a JSON object")
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"LM Studio response was not valid JSON: {exc.msg}") from exc

    if not isinstance(value, dict):
        raise ValueError("LM Studio response root must be a JSON object")
    return value


def _clean_text(value: Any, *, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field} must not be empty")
    return cleaned[:limit]


def normalize_model_response(raw: dict[str, Any]) -> dict[str, Any]:
    reply = _clean_text(raw.get("reply"), field="reply", limit=1200)

    suggestions_raw = raw.get("suggestions")
    if not isinstance(suggestions_raw, list) or len(suggestions_raw) != 2:
        raise ValueError("suggestions must contain exactly two items")

    suggestions: list[dict[str, str]] = []
    for index, item in enumerate(suggestions_raw):
        if isinstance(item, str):
            text = _clean_text(item, field=f"suggestions[{index}]", limit=80)
            suggestion_id = "a" if index == 0 else "b"
        elif isinstance(item, dict):
            text = _clean_text(item.get("text"), field=f"suggestions[{index}].text", limit=80)
            suggestion_id = str(item.get("id") or ("a" if index == 0 else "b"))[:12]
        else:
            raise ValueError(f"suggestions[{index}] must be a string or object")
        suggestions.append({"id": suggestion_id, "text": text})

    state_patch_raw = raw.get("state_patch") if isinstance(raw.get("state_patch"), dict) else {}
    topics_raw = state_patch_raw.get("shared_topics", [])
    topics: list[str] = []
    if isinstance(topics_raw, list):
        for topic in topics_raw[:8]:
            if isinstance(topic, str) and topic.strip():
                topics.append(topic.strip()[:40])

    date_raw = state_patch_raw.get("date") if isinstance(state_patch_raw.get("date"), dict) else {}
    date_status = str(date_raw.get("status") or "none").lower()
    if date_status not in ALLOWED_DATE_STATES:
        date_status = "none"

    def optional_text(value: Any, limit: int = 120) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        return value.strip()[:limit]

    visual_raw = raw.get("visual_moment") if isinstance(raw.get("visual_moment"), dict) else {}
    visual_requested = bool(visual_raw.get("requested", False))
    visual_summary = optional_text(visual_raw.get("summary"), 240)
    if not visual_summary:
        visual_requested = False

    goal_raw = raw.get("goal_tracking") if isinstance(raw.get("goal_tracking"), dict) else {}
    goal_progress = optional_text(goal_raw.get("progress"), 240) or "会話を続けています"

    return {
        "reply": reply,
        "suggestions": suggestions,
        "state_patch": {
            "shared_topics": topics,
            "date": {
                "status": date_status,
                "activity": optional_text(date_raw.get("activity")),
                "time_hint": optional_text(date_raw.get("time_hint")),
            },
        },
        "visual_moment": {
            "requested": visual_requested,
            "summary": visual_summary,
        },
        "goal_tracking": {
            "reached": bool(goal_raw.get("reached", False)),
            "progress": goal_progress,
        },
    }


def merge_state(state: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(state)
    old_topics = merged.get("shared_topics") if isinstance(merged.get("shared_topics"), list) else []
    new_topics = patch.get("shared_topics") if isinstance(patch.get("shared_topics"), list) else []
    topics: list[str] = []
    for topic in [*old_topics, *new_topics]:
        if isinstance(topic, str) and topic not in topics:
            topics.append(topic)
    merged["shared_topics"] = topics[-20:]

    date_patch = patch.get("date") if isinstance(patch.get("date"), dict) else {}
    current_date = merged.get("date") if isinstance(merged.get("date"), dict) else {}
    merged["date"] = {
        "status": date_patch.get("status") or current_date.get("status") or "none",
        "activity": date_patch.get("activity") or current_date.get("activity"),
        "time_hint": date_patch.get("time_hint") or current_date.get("time_hint"),
    }
    merged["turn_count"] = int(merged.get("turn_count", 0)) + 1
    date_goal = (
        merged["date"]["status"] == "accepted"
        and bool(merged["date"]["activity"])
        and bool(merged["date"]["time_hint"])
    )
    goal_patch = patch.get("goal_tracking") if isinstance(patch.get("goal_tracking"), dict) else {}
    merged["goal_reached"] = bool(merged.get("goal_reached")) or bool(goal_patch.get("reached")) or date_goal
    merged["goal_progress"] = str(goal_patch.get("progress") or merged.get("goal_progress") or "会話を続けています")[:240]
    return merged


class ChatProvider(Protocol):
    name: str

    def status(self) -> dict[str, Any]: ...

    def complete(self, session: dict[str, Any], user_message: str) -> dict[str, Any]: ...


@dataclass
class LMStudioProvider:
    base_url: str = "http://127.0.0.1:1234/v1"
    model: str | None = None
    timeout_seconds: float = 60.0
    name: str = "lmstudio"

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")

    @property
    def api_root(self) -> str:
        return self.base_url.removesuffix("/v1")

    def _request_json(
        self,
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.timeout_seconds) as response:
                decoded = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:600]
            raise RuntimeError(f"LM Studio HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"LM Studio connection failed: {exc}") from exc

        try:
            value = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LM Studio returned non-JSON data") from exc
        if not isinstance(value, dict):
            raise RuntimeError("LM Studio returned an unexpected JSON value")
        return value

    def loaded_models(self) -> list[str]:
        try:
            payload = self._request_json(f"{self.api_root}/api/v1/models", timeout=4.0)
        except RuntimeError:
            # Other OpenAI-compatible servers commonly expose only /v1/models.
            payload = self._request_json(f"{self.base_url}/models", timeout=4.0)
        loaded: list[str] = []
        for model in payload.get("models", []):
            if not isinstance(model, dict):
                continue
            for instance in model.get("loaded_instances", []):
                if isinstance(instance, dict) and isinstance(instance.get("id"), str):
                    loaded.append(instance["id"])
        if not loaded:
            for model in payload.get("data", []):
                if isinstance(model, dict) and isinstance(model.get("id"), str):
                    loaded.append(model["id"])
        return loaded

    def selected_model(self) -> str:
        loaded = self.loaded_models()
        if self.model:
            if self.model not in loaded:
                raise RuntimeError(
                    f"Configured model '{self.model}' is not loaded. Loaded models: {loaded or 'none'}"
                )
            return self.model
        if len(loaded) == 1:
            return loaded[0]
        if not loaded:
            raise RuntimeError("No LM Studio model is currently loaded")
        raise RuntimeError(
            "Multiple LM Studio models are loaded; set LM_STUDIO_MODEL explicitly: " + ", ".join(loaded)
        )

    def status(self) -> dict[str, Any]:
        try:
            loaded = self.loaded_models()
            selected = self.selected_model()
            return {"ok": True, "provider": self.name, "model": selected, "loaded_models": loaded}
        except RuntimeError as exc:
            return {"ok": False, "provider": self.name, "error": str(exc)}

    def complete(self, session: dict[str, Any], user_message: str) -> dict[str, Any]:
        character = session["character"]
        state = session["state"]
        scenario = session.get("scenario") if isinstance(session.get("scenario"), dict) else None
        system_prompt = build_system_prompt(character, state, scenario)
        history = session.get("messages", [])[-MAX_HISTORY_MESSAGES:]
        messages = [{"role": "system", "content": system_prompt}]
        for item in history:
            role = item.get("role")
            content = item.get("content")
            if role in {"user", "assistant"} and isinstance(content, str):
                messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_message})

        return normalize_model_response(
            self.complete_json(messages, TURN_RESPONSE_FORMAT, temperature=0.85, max_tokens=700)
        )

    def complete_json(
        self,
        messages: list[dict[str, str]],
        response_format: dict[str, Any],
        *,
        temperature: float = 0.75,
        max_tokens: int = 1200,
    ) -> dict[str, Any]:
        payload = {
            "model": self.selected_model(),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            # Keep compatible reasoning models from spending the response budget
            # before producing the requested JSON.
            "reasoning_effort": "none",
            "stream": False,
            "response_format": response_format,
        }
        try:
            result = self._request_json(
                f"{self.base_url}/chat/completions",
                method="POST",
                payload=payload,
            )
        except RuntimeError as exc:
            if "HTTP 400" not in str(exc) and "HTTP 422" not in str(exc):
                raise
            # Some OpenAI-compatible models do not implement these optional fields.
            fallback_payload = dict(payload)
            fallback_payload.pop("reasoning_effort", None)
            fallback_payload.pop("response_format", None)
            result = self._request_json(
                f"{self.base_url}/chat/completions",
                method="POST",
                payload=fallback_payload,
            )
        try:
            content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("LM Studio response did not include assistant content") from exc
        if not isinstance(content, str):
            raise RuntimeError("LM Studio assistant content was not text")
        return extract_json_object(content)


@dataclass
class DemoProvider:
    name: str = "demo"

    def status(self) -> dict[str, Any]:
        return {"ok": True, "provider": self.name, "model": "deterministic-demo"}

    def complete(self, session: dict[str, Any], user_message: str) -> dict[str, Any]:
        text = user_message.strip()
        turn = int(session.get("state", {}).get("turn_count", 0)) + 1
        invitation = any(word in text for word in ("会わない", "行かない", "行こう", "デート", "一緒に"))
        time_match = re.search(r"(土曜|日曜|週末|平日|来週|明日|午後|午前|夜|昼|\d{1,2}時)", text)
        activity_match = re.search(
            r"(水族館|映画|映画館|喫茶店|カフェ|美術館|公園|散歩|ごはん|食事|ランチ|海|本屋)",
            text,
        )

        if invitation and activity_match and time_match:
            reply = f"うん、行きたい。じゃあ{time_match.group(1)}に、{activity_match.group(1)}で会おうか。"
            date = {
                "status": "accepted",
                "activity": activity_match.group(1),
                "time_hint": time_match.group(1),
            }
            suggestions = [
                {"id": "a", "text": "待ち合わせ場所も決めよう"},
                {"id": "b", "text": "当日、楽しみにしてる"},
            ]
            visual = "約束した場所を思い浮かべ、少し照れながら画面へうなずく"
        elif invitation:
            reply = "会ってみたい。どこへ行くかと、いつがいいか、もう少し一緒に決めたいな。"
            date = {
                "status": "tentative",
                "activity": activity_match.group(1) if activity_match else None,
                "time_hint": time_match.group(1) if time_match else None,
            }
            suggestions = [
                {"id": "a", "text": "週末に水族館へ行かない？"},
                {"id": "b", "text": "行きたい場所はある？"},
            ]
            visual = "予定を考えながら、机のカレンダーへ目を落とす"
        elif "本" in text:
            reply = "静かな話を読んでたよ。読み終わったあとも、部屋に少し残るような本。そっちは最近、何か読んだ？"
            date = {"status": "none", "activity": None, "time_hint": None}
            suggestions = [
                {"id": "a", "text": "今度おすすめを教えて"},
                {"id": "b", "text": "一緒に本屋へ行ってみたい"},
            ]
            visual = "夜の部屋、読みかけの本を手に窓辺でこちらを見る"
        elif "雨" in text:
            reply = "こっちも雨。窓を少し開けると、車の音までやわらかく聞こえるよ。雨の日は好き？"
            date = {"status": "none", "activity": None, "time_hint": None}
            suggestions = [
                {"id": "a", "text": "家で過ごす雨なら好き"},
                {"id": "b", "text": "雨の日の散歩も悪くない"},
            ]
            visual = "雨粒のついた窓辺で、外を眺めてからカメラへ振り返る"
        else:
            reply = f"そうなんだ。ちゃんとその話、もう少し聞きたい。今の気分を一言で言うなら、どんな感じ？"
            date = {"status": "none", "activity": None, "time_hint": None}
            suggestions = [
                {"id": "a", "text": "わりと穏やかな気分"},
                {"id": "b", "text": "少しだけ退屈してる"},
            ]
            visual = "スマートフォンを手に、返事を待ちながらかすかに笑う"

        scenario = session.get("scenario") if isinstance(session.get("scenario"), dict) else {}
        is_date_goal = scenario.get("id") == "date_plan" or "デート" in str(scenario.get("goal") or "")
        reached = date["status"] == "accepted" if is_date_goal else turn >= 3
        progress = "ゴールに必要な話題を確かめています" if not reached else "必要なことを話し合えました"

        return normalize_model_response(
            {
                "reply": reply,
                "suggestions": suggestions,
                "state_patch": {"shared_topics": [text[:24]], "date": date},
                "visual_moment": {"requested": turn % 2 == 1 or invitation, "summary": visual},
                "goal_tracking": {"reached": reached, "progress": progress},
            }
        )


def build_system_prompt(
    character: dict[str, Any], state: dict[str, Any], scenario: dict[str, Any] | None = None
) -> str:
    character_json = json.dumps(character, ensure_ascii=False, indent=2)
    state_json = json.dumps(state, ensure_ascii=False, indent=2)
    scenario_json = json.dumps(scenario or {}, ensure_ascii=False, indent=2)
    return f"""あなたはローカル会話ゲームの一人の登場人物です。

キャラクター設定:
{character_json}

今回のシチュエーションとゴール:
{scenario_json}

現在の会話状態:
{state_json}

規則:
- reply、suggestions内のtext、shared_topics、date内のactivityとtime_hint、visual_moment内のsummaryに入る自然言語は、必ずすべて日本語で書いてください。
- 自然言語を英語や中国語などで代替しないでください。JSONのキー名、suggestionsのid、date.statusの列挙値だけは、指定された英字をそのまま使ってください。
- 日本語で、自然な一対一の雑談を続けてください。
- 設定と直前までの会話で分かった事実を保ってください。
- 今回のシチュエーションを保ち、別の場所や別の出来事へ勝手に切り替えないでください。
- goal_tracking.reachedは、goal_conditionsが会話上で満たされたときだけtrueにしてください。
- goal_tracking.progressには、達成済みの要素または次に必要な要素を短い日本語で書いてください。
- 一度の返答は動画内で約3秒で話せる、自然で短い日本語1文（目安30文字以内）にしてください。
- プレイヤーが次に送れそうな、意味の異なる短い返答案を必ず二つ作ってください。
- 返答案はプレイヤーの発言として書き、選ばなくても会話が成立するようにしてください。
- プレイヤーがデートへ誘った場合、キャラクターとして自然に返答してください。
- date.statusは none / tentative / accepted / declined のいずれかです。
- acceptedは、活動または場所と、日時または時間帯が会話上で具体化した場合に使ってください。
- 好感度の数値は作らないでください。
- visual_moment内のsummaryには、約3秒で見せる表情、視線、手の小さな動作だけを、日本語で一つ書いてください。
- visual_moment内のsummaryには、人物の顔、髪、眼鏡、服、背景、照明、実写・アニメ等の画風を書かず、それらの変更を提案しないでください。
- 説明、Markdown、コードフェンスを付けず、次のJSONだけを返してください。

{{
  "reply": "キャラクターの返答",
  "suggestions": [
    {{"id": "a", "text": "プレイヤーの返答案1"}},
    {{"id": "b", "text": "プレイヤーの返答案2"}}
  ],
  "state_patch": {{
    "shared_topics": ["このターンで共有された短い話題"],
    "date": {{"status": "none", "activity": null, "time_hint": null}}
  }},
  "visual_moment": {{"requested": true, "summary": "映像にする一瞬"}},
  "goal_tracking": {{"reached": false, "progress": "ゴールへ向けた短い進捗"}}
}}"""


class SessionStore:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", session_id):
            raise ValueError("Invalid session id")
        return self.directory / f"{session_id}.json"

    def save(self, session: dict[str, Any]) -> None:
        path = self._path(str(session["id"]))
        serialized = json.dumps(session, ensure_ascii=False, indent=2) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def load(self, session_id: str) -> dict[str, Any]:
        path = self._path(session_id)
        if not path.exists():
            raise FileNotFoundError(session_id)
        return read_json(path)


class ChatService:
    def __init__(self, store: SessionStore, provider: ChatProvider, character: dict[str, Any]):
        self.store = store
        self.provider = provider
        self.character = character

    def new_session(
        self,
        character: dict[str, Any] | None = None,
        scenario: dict[str, Any] | None = None,
        runtime: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session_id = uuid.uuid4().hex
        selected_character = copy.deepcopy(character or self.character)
        selected_scenario = copy.deepcopy(scenario or {})
        greeting = str(
            selected_scenario.get("opening_line")
            or selected_character.get("greeting")
            or "こんばんは。今日はどんな一日だった？"
        )
        suggestions = selected_scenario.get("opening_suggestions") or selected_character.get("opening_suggestions")
        if not isinstance(suggestions, list) or len(suggestions) != 2:
            suggestions = ["今日は少し疲れた", "なんとなく話したくなった"]
        session = {
            "id": session_id,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "character": selected_character,
            "scenario": selected_scenario,
            "runtime": copy.deepcopy(
                runtime or {"provider": {"type": self.provider.name}, "video": {"mode": "none"}}
            ),
            "state": {
                "turn_count": 0,
                "shared_topics": [],
                "date": {"status": "none", "activity": None, "time_hint": None},
                "goal_reached": False,
                "goal_progress": "まだ始まったばかりです",
            },
            "messages": [
                {
                    "id": uuid.uuid4().hex,
                    "role": "assistant",
                    "content": greeting,
                    "created_at": now_iso(),
                    "suggestions": [
                        {"id": "a", "text": str(suggestions[0])[:80]},
                        {"id": "b", "text": str(suggestions[1])[:80]},
                    ],
                    "visual_moment": {"requested": False, "summary": None},
                }
            ],
        }
        self.store.save(session)
        return session

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.store.load(session_id)

    def prepare_send(
        self, session_id: str, user_message: Any, provider: ChatProvider | None = None
    ) -> dict[str, Any]:
        if not isinstance(user_message, str):
            raise ValueError("message must be a string")
        message = user_message.strip()
        if not message:
            raise ValueError("message must not be empty")
        if len(message) > MAX_MESSAGE_CHARS:
            raise ValueError(f"message must be {MAX_MESSAGE_CHARS} characters or fewer")

        session = self.store.load(session_id)
        model_result = (provider or self.provider).complete(session, message)
        timestamp = now_iso()
        session["messages"].append(
            {
                "id": uuid.uuid4().hex,
                "role": "user",
                "content": message,
                "created_at": timestamp,
            }
        )
        assistant_message = {
            "id": uuid.uuid4().hex,
            "role": "assistant",
            "content": model_result["reply"],
            "created_at": now_iso(),
            "suggestions": model_result["suggestions"],
            "visual_moment": model_result["visual_moment"],
        }
        session["messages"].append(assistant_message)
        state_patch = dict(model_result["state_patch"])
        state_patch["goal_tracking"] = model_result["goal_tracking"]
        session["state"] = merge_state(session["state"], state_patch)
        session["updated_at"] = now_iso()
        return session

    def save_session(self, session: dict[str, Any]) -> None:
        self.store.save(session)

    def send(self, session_id: str, user_message: Any) -> dict[str, Any]:
        session = self.prepare_send(session_id, user_message)
        self.save_session(session)
        return session
