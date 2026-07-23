import unittest
import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "app" / "services" / "novel_skill_service.py"
SPEC = importlib.util.spec_from_file_location("novel_skill_service", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)
novel_skill_prompt = MODULE.novel_skill_prompt


class NovelSkillPromptTests(unittest.TestCase):
    def test_custom_prompt_is_composed_after_mandatory_rules(self):
        prompt = novel_skill_prompt("draft", "使用冷峻克制的文风")
        self.assertIn("novel-continuity-writer", prompt)
        self.assertIn("不得改变上下文中的姓名", prompt)
        self.assertIn("使用冷峻克制的文风", prompt)

    def test_all_runtime_phases_are_available(self):
        for phase in ("outline", "draft", "next", "memory"):
            with self.subTest(phase=phase):
                self.assertGreater(len(novel_skill_prompt(phase)), 100)

    def test_unknown_phase_is_rejected(self):
        with self.assertRaises(ValueError):
            novel_skill_prompt("publish")


if __name__ == "__main__":
    unittest.main()
