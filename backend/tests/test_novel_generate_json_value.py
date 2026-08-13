from app.services.novel_generate_service import _json_value


def test_json_value_parses_non_empty_json_object():
    assert _json_value('{"stages": [{"name": "开篇"}]}', {}) == {
        "stages": [{"name": "开篇"}]
    }


def test_json_value_returns_default_for_empty_or_invalid_json():
    fallback = {"stages": []}

    assert _json_value(None, fallback) is fallback
    assert _json_value("", fallback) is fallback
    assert _json_value("not-json", fallback) is fallback
