from app.services.novel_generate_service import _normalize_chapter_generation_mode


def test_rejected_candidate_restart_wins_without_formal_content():
    assert _normalize_chapter_generation_mode(True, True, False) == (False, True)


def test_formal_regeneration_is_preserved_when_saved_content_exists():
    assert _normalize_chapter_generation_mode(True, False, True) == (True, False)


def test_initial_generation_remains_plain_generation():
    assert _normalize_chapter_generation_mode(False, False, False) == (False, False)
