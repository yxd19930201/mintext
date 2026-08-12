import json

from app.schemas.novel_generate import (
    BatchGenerateChaptersRequest,
    GenerateChapterRequest,
    GenerateNextChapterRequest,
    GenerateNovelOutlineRequest,
)
from app.services.ai_usage_service import AIUsageService


def test_generation_requests_default_to_strict_backend_contract():
    # The desktop client explicitly opts into economy mode. Keeping the API
    # default false protects older integrations from silently changing quality.
    assert GenerateNovelOutlineRequest(novel_id=1, total_chapters=10).economy_mode is False
    assert GenerateChapterRequest().economy_mode is False
    assert BatchGenerateChaptersRequest().economy_mode is False
    assert GenerateNextChapterRequest().economy_mode is False


def test_free_generation_contract_defaults_to_deepseek():
    request = GenerateChapterRequest(free_mode=True)
    assert request.free_mode is True
    assert request.free_provider == "deepseek"


def test_web_ai_config_uses_local_adapter(monkeypatch):
    from app.config import settings
    from app.services.ai_service import ai_service

    monkeypatch.setattr(settings, "MINITEXT_WEB_AI_URL", "http://127.0.0.1:4999/")
    config = ai_service.web_config("chatgpt")
    assert config.base_url == "http://127.0.0.1:4999/v1"
    assert config.model == "chatgpt"
    assert config.input_price_cny == 0


def test_usage_tracker_persists_tokens_and_estimated_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("MINITEXT_DATA_DIR", str(tmp_path))
    tracker = AIUsageService()

    tracker.record(
        model="deepseek-chat",
        prompt_tokens=1_000_000,
        completion_tokens=500_000,
        input_price_cny=2,
        output_price_cny=8,
    )

    stats = tracker.summary()
    assert stats["calls"] == 1
    assert stats["prompt_tokens"] == 1_000_000
    assert stats["completion_tokens"] == 500_000
    assert stats["total_tokens"] == 1_500_000
    assert stats["estimated_cost_cny"] == 6
    assert stats["by_model"]["deepseek-chat"]["calls"] == 1
    assert json.loads((tmp_path / "ai_usage.json").read_text(encoding="utf-8"))["calls"] == 1


def test_usage_tracker_reset_keeps_valid_zero_summary(tmp_path, monkeypatch):
    monkeypatch.setenv("MINITEXT_DATA_DIR", str(tmp_path))
    tracker = AIUsageService()
    tracker.record("model", 100, 50, 1, 1)

    reset = tracker.reset()

    assert reset["calls"] == 0
    assert reset["total_tokens"] == 0
    assert reset["estimated_cost_cny"] == 0
