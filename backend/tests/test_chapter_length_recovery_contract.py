from pathlib import Path


def test_chapter_generation_has_bounded_length_recovery():
    source = Path("app/services/novel_generate_service.py").read_text(encoding="utf-8")

    assert "最终正文绝对不得少于4200字或超过6200字" in source
    assert "final_local and all(" in source
    assert 'str(item.get("type") or "").lower() == "length"' in source


def test_revision_prompt_has_hard_length_window():
    source = Path("app/services/ai_service.py").read_text(encoding="utf-8")

    assert "硬性范围4200—6200字" in source
    assert "删除重复回顾与同义复述" in source
