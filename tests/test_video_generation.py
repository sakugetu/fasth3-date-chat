from __future__ import annotations

import unittest

from app.video_generation import (
    DEFAULT_CHARACTER_SEED,
    FRAMES,
    HEIGHT,
    WIDTH,
    build_video_prompt,
    build_workflow,
)


class VideoGenerationTests(unittest.TestCase):
    def test_prompt_contains_exact_japanese_dialogue(self) -> None:
        dialogue = "そうなんだ。もう少し聞かせて？"
        prompt = build_video_prompt(
            {"name": "澪", "visual_anchor": "黒髪、銀縁眼鏡、紺色のカーディガン"},
            dialogue,
            "こちらを見て微笑む",
        )
        self.assertIn(dialogue, prompt)
        self.assertIn("speaks only Japanese", prompt)
        self.assertIn("says nothing else", prompt)

    def test_prompt_keeps_visual_identity_block_immutable(self) -> None:
        visual_prompt = "Photorealistic live-action footage of the same woman. Never switch to anime."
        prompt = build_video_prompt(
            {"name": "澪", "visual_prompt": visual_prompt},
            "少し照れるね。",
            "視線を少し逸らして微笑む",
        )
        self.assertIn(visual_prompt, prompt)
        self.assertIn("IMMUTABLE CHARACTER AND STYLE BLOCK", prompt)
        self.assertIn("must not change identity", prompt)

    def test_omni_prompt_names_the_picture_reference(self) -> None:
        prompt = build_video_prompt(
            {"name": "澪", "visual_prompt": "同じ人物"},
            "こんばんは。",
            "少し微笑む",
            reference_mode="omni",
        )
        self.assertIn("<Picture 1>", prompt)
        self.assertIn("exact identity reference", prompt)

    def test_workflow_uses_fast_low_resolution_profile(self) -> None:
        workflow = build_workflow("テスト", 123, "video/test")
        inputs = workflow["5"]["inputs"]
        self.assertEqual((inputs["width"], inputs["height"]), (WIDTH, HEIGHT))
        self.assertEqual((WIDTH, HEIGHT, FRAMES), (320, 320, 72))
        self.assertEqual(workflow["9"]["inputs"]["steps"], 4)
        self.assertEqual(workflow["19"]["inputs"]["selection"], "VSA (FastVideo)")
        self.assertEqual(DEFAULT_CHARACTER_SEED, 986429173)

    def test_omni_workflow_uses_reference_node_and_image(self) -> None:
        workflow = build_workflow(
            "<Picture 1> テスト", 123, "video/test",
            reference_mode="omni", reference_image="character.png",
        )
        self.assertEqual(workflow["5"]["class_type"], "MiniMaxH3ReferenceToVideo")
        self.assertEqual(workflow["5"]["inputs"]["audio_vae"], ["4", 0])
        self.assertEqual(workflow["5"]["inputs"]["ref_images.ref_image_0"], ["100", 0])
        self.assertEqual(workflow["100"]["inputs"]["image"], "character.png")

    def test_first_frame_workflow_uses_image_to_video_node(self) -> None:
        workflow = build_workflow(
            "テスト", 123, "video/test",
            reference_mode="first_frame", reference_image="character.webp",
        )
        self.assertEqual(workflow["5"]["class_type"], "MiniMaxH3ImageToVideo")
        self.assertEqual(workflow["5"]["inputs"]["first_frame"], ["100", 0])

    def test_workflow_rejects_missing_reference_image(self) -> None:
        with self.assertRaisesRegex(ValueError, "参照画像"):
            build_workflow("テスト", 123, "video/test", reference_mode="omni")


if __name__ == "__main__":
    unittest.main()
