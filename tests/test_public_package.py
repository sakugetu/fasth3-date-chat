from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.server import DEFAULT_CHARACTER_PATH, DEFAULT_OPENING_PATH, create_service
from tools.release_audit import audit


ROOT = Path(__file__).resolve().parents[1]


class PublicPackageTests(unittest.TestCase):
    def test_demo_service_starts_from_example_character(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = __import__("app.server", fromlist=["SESSIONS_ROOT"])
            previous = original.SESSIONS_ROOT
            original.SESSIONS_ROOT = Path(directory)
            try:
                service = create_service("demo", DEFAULT_CHARACTER_PATH)
                session = service.new_session()
            finally:
                original.SESSIONS_ROOT = previous
        self.assertEqual(len(session["messages"][0]["suggestions"]), 2)

    def test_opening_video_is_packaged(self) -> None:
        self.assertTrue(DEFAULT_OPENING_PATH.is_file())

    def test_mobile_settings_use_the_full_viewport(self) -> None:
        html = (ROOT / "app" / "static" / "index.html").read_text(encoding="utf-8")
        css = (ROOT / "app" / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn('<body class="is-start-screen">', html)
        self.assertIn("body.is-start-screen .scene-frame", css)
        self.assertIn("height: 100dvh", css)

    def test_release_tree_has_no_generic_local_data(self) -> None:
        self.assertEqual(audit(ROOT, []), [])


if __name__ == "__main__":
    unittest.main()
