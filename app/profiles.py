from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any


CHARACTER_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "conversation_character",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "name": {"type": "string"},
                "tagline": {"type": "string"},
                "relationship": {"type": "string"},
                "personality": {"type": "string"},
                "speaking_style": {"type": "string"},
                "known_facts": {"type": "array", "minItems": 3, "maxItems": 5, "items": {"type": "string"}},
                "visual_anchor": {"type": "string"},
                "visual_prompt": {"type": "string"},
                "greeting": {"type": "string"},
                "opening_suggestions": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string"}},
            },
            "required": [
                "name", "tagline", "relationship", "personality", "speaking_style",
                "known_facts", "visual_anchor", "visual_prompt", "greeting", "opening_suggestions",
            ],
        },
    },
}


SCENARIO_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "conversation_scenario",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "title": {"type": "string"},
                "tagline": {"type": "string"},
                "setup": {"type": "string"},
                "character_role": {"type": "string"},
                "goal": {"type": "string"},
                "goal_conditions": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
                "tone": {"type": "string"},
                "visual_context": {"type": "string"},
                "opening_line": {"type": "string"},
                "opening_suggestions": {"type": "array", "minItems": 2, "maxItems": 2, "items": {"type": "string"}},
            },
            "required": [
                "title", "tagline", "setup", "character_role", "goal", "goal_conditions",
                "tone", "visual_context", "opening_line", "opening_suggestions",
            ],
        },
    },
}


BUILTIN_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "night_chat",
        "title": "夜の雑談",
        "tagline": "眠る前の短いビデオ通話",
        "setup": "夜、ふたりはそれぞれの部屋からビデオ通話をしている。急がず、今日の出来事や今の気分を話す。",
        "character_role": "親しくなりかけている相手。自分のことも少しずつ話し、相手の返事を待つ。",
        "goal": "お互いに今日の出来事と今の気分を一つずつ共有し、自然に『また話そう』と言えるところまで会話する。",
        "goal_conditions": ["双方の今日の出来事が一つずつ分かる", "双方の今の気分が分かる", "次も話したい意思が確認できる"],
        "tone": "静かで親しみのある日常会話。大げさな事件は起こさない。",
        "visual_context": "夜のビデオ通話。顔を中心にした近距離の画角。",
        "opening_line": "こんばんは。ちょうど少し話したいと思ってた。今日は、どんな一日だった？",
        "opening_suggestions": ["今日は少し疲れた", "なんとなく話したくなった"],
    },
    {
        "id": "date_plan",
        "title": "デートの約束",
        "tagline": "行き先と日時を決める",
        "setup": "夜のビデオ通話中。ふたりはまだ直接会ったことがなく、会ってみたい気持ちを探っている。",
        "character_role": "誘いを一方的に受けるだけでなく、自分の希望や都合も自然に伝える。",
        "goal": "ふたりで出かける場所または活動と、日時または時間帯を具体的に決める。",
        "goal_conditions": ["一緒に出かける合意がある", "場所または活動が決まる", "日時または時間帯が決まる"],
        "tone": "少し照れのある、現実的で穏やかな相談。",
        "visual_context": "夜のビデオ通話。表情が読める顔中心の画角。",
        "opening_line": "ねえ、前に話してたお店、ちょっと気になってるんだ。",
        "opening_suggestions": ["今度、一緒に行ってみる？", "どんなお店だったっけ？"],
    },
    {
        "id": "tomorrow_courage",
        "title": "明日の背中押し",
        "tagline": "不安をほどいて準備を決める",
        "setup": "相手は明日の発表を前に少し緊張して、夜にビデオ通話をかけてきた。",
        "character_role": "不安を正直に話すが、相手の提案を材料に自分で次の一歩を選ぶ。",
        "goal": "不安の理由を一つ言葉にし、今夜できる具体的な準備を一つ決めて、通話を前向きに終える。",
        "goal_conditions": ["不安の理由が分かる", "今夜する準備が一つ決まる", "本人がやってみると意思表示する"],
        "tone": "励ましすぎず、相手の気持ちを聞く穏やかな会話。",
        "visual_context": "机の前からのビデオ通話。顔を中心に、手元のメモが時々見える。",
        "opening_line": "明日の発表、ちょっとだけ緊張してきた。少し付き合ってくれる？",
        "opening_suggestions": ["もちろん。何が一番不安？", "まず一回、深呼吸しよう"],
    },
    {
        "id": "postcard_mystery",
        "title": "古い絵葉書の謎",
        "tagline": "三つの手掛かりから場所を当てる",
        "setup": "相手が古本から出てきた宛名のない絵葉書をビデオ通話で見せる。裏面には場所を示す三つの手掛かりがある。",
        "character_role": "手掛かりを一度に全部言わず、会話に応じて一つずつ読み上げ、一緒に推理する。正解は『海辺の古い時計台』。",
        "goal": "三つの手掛かりを確認し、絵葉書が示す『海辺の古い時計台』へたどり着く。",
        "goal_conditions": ["三つの手掛かりが会話に出る", "海辺と時計の要素を結びつける", "海辺の古い時計台と答える"],
        "tone": "怖くない、こぢんまりとした不思議な日常ミステリー。",
        "visual_context": "絵葉書をカメラ近くに持つビデオ通話。基本は顔中心の画角。",
        "opening_line": "古本から変な絵葉書が出てきたの。少しだけ謎解き、手伝ってくれない？",
        "opening_suggestions": ["表には何が写ってる？", "裏の文章を読んでみて"],
    },
    {
        "id": "weekend_trip",
        "title": "週末の小旅行",
        "tagline": "ふたりに合う一日を組み立てる",
        "setup": "週末に日帰りで出かける相談をビデオ通話で始める。候補は海辺、古い町並み、森の湖。",
        "character_role": "静かな場所が好きだが、相手の希望も聞いて、移動や過ごし方を一緒に決める。",
        "goal": "行き先、そこで一番したいこと、出発する時間帯の三つを決める。",
        "goal_conditions": ["三候補から行き先が決まる", "現地で一番したいことが決まる", "出発する時間帯が決まる"],
        "tone": "旅行前のわくわく感がある、具体的で落ち着いた相談。",
        "visual_context": "地図をそばに置いたビデオ通話。顔中心の近距離画角。",
        "opening_line": "週末、少し遠くへ行ってみたいな。海と古い町と森なら、どれがいい？",
        "opening_suggestions": ["海辺でのんびりしたい", "古い町を歩いてみたい"],
    },
]


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be empty")
    return value.strip()[:limit]


def _string_list(value: Any, field: str, *, minimum: int, maximum: int, item_limit: int) -> list[str]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} must contain between {minimum} and {maximum} items")
    return [_text(item, f"{field} item", item_limit) for item in value]


def stable_seed(profile: dict[str, Any]) -> int:
    source = json.dumps(profile, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return int.from_bytes(hashlib.sha256(source).digest()[:8], "big") % (2**63 - 1)


def normalize_character(raw: dict[str, Any]) -> dict[str, Any]:
    profile = {
        "name": _text(raw.get("name"), "name", 40),
        "tagline": _text(raw.get("tagline"), "tagline", 100),
        "relationship": _text(raw.get("relationship"), "relationship", 500),
        "personality": _text(raw.get("personality"), "personality", 600),
        "speaking_style": _text(raw.get("speaking_style"), "speaking_style", 400),
        "known_facts": _string_list(raw.get("known_facts"), "known_facts", minimum=3, maximum=5, item_limit=160),
        "visual_anchor": _text(raw.get("visual_anchor"), "visual_anchor", 600),
        "visual_prompt": _text(raw.get("visual_prompt"), "visual_prompt", 1800),
        "greeting": _text(raw.get("greeting"), "greeting", 180),
        "opening_suggestions": _string_list(raw.get("opening_suggestions"), "opening_suggestions", minimum=2, maximum=2, item_limit=80),
    }
    seed = raw.get("generation_seed")
    profile["generation_seed"] = int(seed) if isinstance(seed, int) and 0 <= seed < 2**63 else stable_seed(profile)
    return profile


def normalize_scenario(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _text(raw.get("title"), "title", 60),
        "tagline": _text(raw.get("tagline"), "tagline", 120),
        "setup": _text(raw.get("setup"), "setup", 800),
        "character_role": _text(raw.get("character_role"), "character_role", 600),
        "goal": _text(raw.get("goal"), "goal", 500),
        "goal_conditions": _string_list(raw.get("goal_conditions"), "goal_conditions", minimum=1, maximum=4, item_limit=220),
        "tone": _text(raw.get("tone"), "tone", 300),
        "visual_context": _text(raw.get("visual_context"), "visual_context", 400),
        "opening_line": _text(raw.get("opening_line"), "opening_line", 180),
        "opening_suggestions": _string_list(raw.get("opening_suggestions"), "opening_suggestions", minimum=2, maximum=2, item_limit=80),
    }


def character_generation_messages(description: str) -> tuple[str, str]:
    description = _text(description, "description", 1600)
    system = """会話ゲーム用のキャラクター設定をJSONで設計してください。入力の意図を保ち、説明にない価値判断や物語上の制限を加えないでください。
name、tagline、relationship、personality、speaking_style、known_facts、visual_anchor、greeting、opening_suggestionsは自然な日本語で書いてください。
visual_promptだけはFastH3へ毎ターン共通投入する英語の固定外見プロンプトです。顔立ち、髪型、服装、画風、照明、部屋、顔中心の近距離画角を具体的にし、全ターンで同一人物・同一衣装・同一画風を維持する命令を含めてください。
greetingは短い日本語一文、opening_suggestionsはプレイヤー側の短い日本語二択です。説明やMarkdownを付けず、指定JSONだけを返してください。"""
    return system, f"この日本語説明からキャラクターを作ってください:\n{description}"


def scenario_generation_messages(description: str) -> tuple[str, str]:
    description = _text(description, "description", 1800)
    system = """一対一のビデオ通話で進む短い会話ゲームのシチュエーションをJSONで設計してください。入力の意図を保ち、説明にない価値判断や物語上の制限を加えないでください。
すべての自然言語を日本語で書いてください。goalは会話で達成を判定できる具体的な終点にし、goal_conditionsを1〜4個に分けてください。opening_lineは登場人物の短い第一声、opening_suggestionsはプレイヤー側の意味が異なる短い日本語二択です。
映像は顔中心の近距離ビデオ通話が基本なので、visual_contextもその画面で理解できる形にしてください。説明やMarkdownを付けず、指定JSONだけを返してください。"""
    return system, f"この日本語説明からシチュエーションとゴールを作ってください:\n{description}"


class JsonProfileStore:
    def __init__(self, directory: Path, kind: str):
        self.directory = directory
        self.kind = kind
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", profile_id):
            raise ValueError(f"Invalid {self.kind} id")
        return self.directory / f"{profile_id}.json"

    def save(self, profile: dict[str, Any]) -> dict[str, Any]:
        profile_id = uuid.uuid4().hex
        value = {"id": profile_id, **profile}
        path = self._path(profile_id)
        fd, temporary = tempfile.mkstemp(prefix=f".{profile_id}-", suffix=".tmp", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return value

    def load(self, profile_id: str) -> dict[str, Any]:
        path = self._path(profile_id)
        if not path.is_file():
            raise FileNotFoundError(profile_id)
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError(f"Invalid {self.kind} profile")
        return value

    def list(self) -> list[dict[str, Any]]:
        values: list[dict[str, Any]] = []
        for path in sorted(self.directory.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
            try:
                value = self.load(path.stem)
            except (ValueError, OSError, json.JSONDecodeError):
                continue
            values.append(value)
        return values
