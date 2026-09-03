from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.date_chat import (
    ChatService,
    DemoProvider,
    SessionStore,
    TURN_RESPONSE_FORMAT,
    build_system_prompt,
    extract_json_object,
    normalize_model_response,
)


CHARACTER = {
    "name": "澪",
    "greeting": "こんばんは。少し話していかない？",
    "opening_suggestions": ["今日はどんな日だった？", "いま何してた？"],
}


class DateChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = SessionStore(Path(self.temp_dir.name))
        self.service = ChatService(self.store, DemoProvider(), CHARACTER)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_extracts_fenced_json(self) -> None:
        parsed = extract_json_object('```json\n{"reply":"ok"}\n```')
        self.assertEqual(parsed["reply"], "ok")

    def test_normalizer_requires_exactly_two_suggestions(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly two"):
            normalize_model_response({"reply": "ok", "suggestions": ["one"]})

    def test_prompt_requires_all_natural_language_in_japanese(self) -> None:
        prompt = build_system_prompt(CHARACTER, {"turn_count": 0})
        self.assertIn("必ずすべて日本語", prompt)
        self.assertIn("自然言語を英語や中国語などで代替しない", prompt)
        self.assertIn("表情、視線、手の小さな動作だけ", prompt)
        self.assertIn("画風を書かず", prompt)

    def test_lmstudio_response_schema_requires_two_suggestions(self) -> None:
        suggestions = TURN_RESPONSE_FORMAT["json_schema"]["schema"]["properties"]["suggestions"]
        self.assertEqual(suggestions["minItems"], 2)
        self.assertEqual(suggestions["maxItems"], 2)

    def test_new_session_has_two_suggestions_and_persists(self) -> None:
        created = self.service.new_session()
        self.assertEqual(len(created["messages"][0]["suggestions"]), 2)
        loaded = self.service.get_session(created["id"])
        self.assertEqual(loaded["id"], created["id"])

    def test_scenario_and_character_are_snapshotted_into_session(self) -> None:
        character = {**CHARACTER, "name": "凪"}
        scenario = {
            "id": "rainy_call",
            "title": "雨の通話",
            "goal": "明日の予定を一つ決める",
            "opening_line": "雨、まだ降ってる？",
            "opening_suggestions": ["まだ降ってるよ", "もう止んだみたい"],
        }
        created = self.service.new_session(character, scenario)
        character["name"] = "変更後"
        scenario["goal"] = "変更後"
        self.assertEqual(created["character"]["name"], "凪")
        self.assertEqual(created["scenario"]["goal"], "明日の予定を一つ決める")
        self.assertEqual(created["messages"][0]["content"], "雨、まだ降ってる？")
        self.assertEqual(created["messages"][0]["suggestions"][0]["text"], "まだ降ってるよ")

    def test_chat_keeps_two_suggestions(self) -> None:
        session = self.service.new_session()
        updated = self.service.send(session["id"], "今日は雨だね")
        self.assertEqual(len(updated["messages"]), 3)
        self.assertEqual(len(updated["messages"][-1]["suggestions"]), 2)
        self.assertEqual(updated["state"]["turn_count"], 1)

    def test_concrete_invitation_reaches_goal(self) -> None:
        session = self.service.new_session()
        updated = self.service.send(session["id"], "週末に一緒に水族館へ行かない？")
        date = updated["state"]["date"]
        self.assertEqual(date["status"], "accepted")
        self.assertEqual(date["activity"], "水族館")
        self.assertEqual(date["time_hint"], "週末")
        self.assertTrue(updated["state"]["goal_reached"])

    def test_empty_message_is_rejected_without_changing_session(self) -> None:
        session = self.service.new_session()
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            self.service.send(session["id"], "   ")
        loaded = self.service.get_session(session["id"])
        self.assertEqual(len(loaded["messages"]), 1)


if __name__ == "__main__":
    unittest.main()
