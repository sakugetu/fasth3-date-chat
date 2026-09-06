from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app.date_chat import ChatService, DemoProvider, SessionStore, read_json
from app.profiles import BUILTIN_SCENARIOS, JsonProfileStore, normalize_character
from app.server import (
    DEFAULT_CHARACTER_PATH, DEFAULT_OPENING_PATH, DEFAULT_REFERENCE_PATH,
    DateChatHTTPServer, Handler,
)


class OpeningVideoTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.server = DateChatHTTPServer(("127.0.0.1", 0), Handler)
        self.server.service = ChatService(
            SessionStore(root / "sessions"), DemoProvider(),
            normalize_character(read_json(DEFAULT_CHARACTER_PATH)),
        )
        self.server.character_store = JsonProfileStore(root / "characters", "character")
        self.server.scenario_store = JsonProfileStore(root / "scenarios", "scenario")
        self.server.opening_path = DEFAULT_OPENING_PATH
        self.server.defaults = {
            "provider": {"type": "demo", "base_url": "http://127.0.0.1:1234/v1"},
            "video": {"mode": "fasth3", "base_url": "http://127.0.0.1:8002"},
        }
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        generator_patch = patch("app.server.FastH3VideoGenerator")
        self.generator = generator_patch.start()
        self.addCleanup(generator_patch.stop)
        self.generator.return_value.generate.return_value = {"video_url": "/media/test-opening.mp4"}

    def stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def start(self, *, mode="fasth3", reference="default", reference_mode="omni", **extra):
        body = {
            "video": {"mode": mode, "reference_image_id": reference, "reference_mode": reference_mode},
            **extra,
        }
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_port}/api/sessions",
            data=json.dumps(body).encode(), headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 201)
            session = json.load(response)
        self.assertEqual(session, self.server.service.get_session(session["id"]))
        return session

    def test_default_opening_plays_without_generation_in_both_reference_modes(self):
        for mode in ("omni", "first_frame"):
            with self.subTest(mode=mode):
                session = self.start(reference_mode=mode)
                self.assertEqual(session["opening_video_url"], "/media/opening.mp4")
        self.generator.assert_not_called()

    def test_missing_opening_generates_first_line_with_selected_reference_mode(self):
        self.server.opening_path = Path(self.directory.name) / "missing.mp4"
        for mode in ("omni", "first_frame"):
            with self.subTest(mode=mode):
                session = self.start(reference_mode=mode)
                args = self.generator.return_value.generate.call_args.kwargs
                message = session["messages"][0]
                self.assertEqual(args["dialogue"], message["content"])
                self.assertEqual(args["message_id"], message["id"])
                self.assertEqual(args["reference_path"], DEFAULT_REFERENCE_PATH)
                self.assertEqual(args["reference_mode"], mode)
                self.assertEqual(session["opening_video_url"], message["visual_moment"]["video_url"])
                self.assertTrue(message["visual_moment"]["requested"])
                self.assertEqual(session["state"]["turn_count"], 0)
                self.assertEqual(len(session["messages"]), 1)

    def test_custom_reference_does_not_play_bundled_character(self):
        with patch("app.server.reference_image_path", return_value=Path("custom.png")):
            session = self.start(reference="a" * 32)
        self.assertEqual(session["opening_video_url"], "/media/test-opening.mp4")
        self.assertEqual(self.generator.return_value.generate.call_args.kwargs["reference_path"], Path("custom.png"))

    def test_different_scenario_uses_its_opening_line(self):
        scenario = BUILTIN_SCENARIOS[1]
        self.start(scenario_id=scenario["id"])
        self.assertEqual(self.generator.return_value.generate.call_args.kwargs["dialogue"], scenario["opening_line"])

    def test_custom_character_generates_its_own_opening(self):
        character = {**self.server.service.character, "name": "Custom"}
        saved = self.server.character_store.save(character)
        self.start(character_id=saved["id"])
        self.assertEqual(self.generator.return_value.generate.call_args.kwargs["character"]["name"], "Custom")

    def test_video_disabled_never_generates_when_opening_missing(self):
        self.server.opening_path = Path(self.directory.name) / "missing.mp4"
        session = self.start(mode="none", reference=None)
        self.assertIsNone(session["opening_video_url"])
        self.generator.assert_not_called()

    def test_generation_failure_is_returned_instead_of_silent_static_start(self):
        self.server.opening_path = Path(self.directory.name) / "missing.mp4"
        self.generator.return_value.generate.side_effect = RuntimeError("generation failed")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.start()
        self.assertEqual(error.exception.code, 502)
        self.assertEqual(json.load(error.exception)["error"], "generation failed")


if __name__ == "__main__":
    unittest.main()
