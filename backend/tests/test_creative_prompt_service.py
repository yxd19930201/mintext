import unittest

from app.services.creative_prompt_service import creative_prompt


class CreativePromptServiceTests(unittest.TestCase):
    def test_every_non_novel_ai_phase_has_built_in_rules(self):
        phases = (
            "short_outline", "short_script", "short_next",
            "script_improve", "novel_to_short", "storyboard",
        )
        for phase in phases:
            with self.subTest(phase=phase):
                self.assertGreater(len(creative_prompt(phase)), 100)

    def test_project_requirements_cannot_replace_built_in_prompt(self):
        prompt = creative_prompt("short_script", "喜剧风格")
        self.assertIn("可直接排演和拍摄", prompt)
        self.assertIn("喜剧风格", prompt)
        self.assertLess(prompt.index("可直接排演和拍摄"), prompt.index("喜剧风格"))

    def test_unknown_phase_is_rejected(self):
        with self.assertRaises(ValueError):
            creative_prompt("unknown")


if __name__ == "__main__":
    unittest.main()
