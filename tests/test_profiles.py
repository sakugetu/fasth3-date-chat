from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.profiles import (
    BUILTIN_SCENARIOS,
    JsonProfileStore,
    character_generation_messages,
    normalize_character,
    normalize_scenario,
    scenario_generation_messages,
    stable_seed,
)


CHARACTER = {
    "name": "凪",
    "tagline": "静かな話し相手",
    "relationship": "最近知り合った相手",
    "personality": "落ち着いていて好奇心がある",
    "speaking_style": "短い自然な日本語で話す",
    "known_facts": ["本が好き", "夜型", "紅茶が好き"],
    "visual_anchor": "短い黒髪と青いシャツ",
    "visual_prompt": "The same adult woman, close-up video call, identical blue shirt in every shot.",
    "greeting": "こんばんは。少し話す？",
    "opening_suggestions": ["うん、話そう", "今日は何してた？"],
}


class ProfileTests(unittest.TestCase):
    def test_five_builtin_scenarios_have_concrete_goals(self) -> None:
        self.assertEqual(len(BUILTIN_SCENARIOS), 5)
        for raw in BUILTIN_SCENARIOS:
            scenario = normalize_scenario(raw)
            self.assertTrue(scenario["goal"])
            self.assertGreaterEqual(len(scenario["goal_conditions"]), 1)
            self.assertEqual(len(scenario["opening_suggestions"]), 2)

    def test_character_seed_is_stable_and_profile_is_valid(self) -> None:
        first = normalize_character(CHARACTER)
        second = normalize_character(CHARACTER)
        self.assertEqual(first["generation_seed"], second["generation_seed"])
        self.assertEqual(first["generation_seed"], stable_seed({k: v for k, v in first.items() if k != "generation_seed"}))

    def test_profile_store_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = JsonProfileStore(Path(directory), "character")
            saved = store.save(normalize_character(CHARACTER))
            loaded = store.load(saved["id"])
        self.assertEqual(loaded["name"], "凪")
        self.assertEqual(len(saved["id"]), 32)

    def test_generation_prompts_require_japanese_and_fixed_visual_identity(self) -> None:
        character_system, character_user = character_generation_messages("赤い髪の人物")
        scenario_system, scenario_user = scenario_generation_messages("雨の夜に相談する")
        self.assertIn("自然な日本語", character_system)
        self.assertIn("全ターンで同一人物", character_system)
        self.assertIn("赤い髪", character_user)
        self.assertIn("すべての自然言語を日本語", scenario_system)
        self.assertIn("goal_conditions", scenario_system)
        self.assertIn("雨の夜", scenario_user)


if __name__ == "__main__":
    unittest.main()
