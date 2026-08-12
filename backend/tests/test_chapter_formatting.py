from app.services.ai_service import normalize_chapter_paragraphs


def test_preserves_existing_paragraph_structure():
    source = "第一段。\n\n第二段。\n\n第三段。"
    assert normalize_chapter_paragraphs(source) == source


def test_repairs_long_single_line_chapter_without_changing_words():
    source = "".join(
        f"林墨核对第{index}项线索，确认时间与证物记录能够对应。"
        for index in range(1, 70)
    )
    formatted = normalize_chapter_paragraphs(source)

    assert "\n\n" in formatted
    assert formatted.replace("\n", "") == source
    assert all(paragraph.strip() for paragraph in formatted.split("\n\n"))


def test_does_not_reformat_short_summary():
    source = "林墨发现新的符号，并决定继续追查。"
    assert normalize_chapter_paragraphs(source) == source
