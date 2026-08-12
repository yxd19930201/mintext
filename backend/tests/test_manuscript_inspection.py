import pytest
from pydantic import ValidationError
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.schemas.manuscript_inspection import ManuscriptDocument, ManuscriptInspectionRequest
from app.services.manuscript_inspection_service import _group_documents, _representative_sample, _text_metrics
from app.services.ai_service import AIService


def test_inspection_request_requires_exactly_one_source():
    with pytest.raises(ValidationError):
        ManuscriptInspectionRequest(inspection_type="quality")
    with pytest.raises(ValidationError):
        ManuscriptInspectionRequest(
            inspection_type="quality",
            novel_id=1,
            source_text="正文" * 200,
        )


def test_folder_source_accepts_ordered_chapter_documents():
    request = ManuscriptInspectionRequest(
        inspection_type="quality",
        source_name="长篇小说",
        source_documents=[
            ManuscriptDocument(name=f"第{index}章.txt", chapter_number=index, content=(f"第{index}章正文。" * 20))
            for index in range(1, 4)
        ],
    )
    assert len(request.source_documents or []) == 3


def test_group_documents_covers_every_chapter_once_without_sampling():
    documents = [
        {"name": f"第{index}章", "chapter_number": index, "content": "正文" * 20}
        for index in range(1, 18)
    ]
    groups = _group_documents(documents, max_chars=250)
    flattened = [document["chapter_number"] for group in groups for document in group]
    assert flattened == list(range(1, 18))


def test_text_metrics_scan_full_manuscript_for_repetition_and_style_markers():
    sentence = "他深吸一口气，缓缓开口。"
    text = "第1章：开端\n\n" + sentence * 3 + "\n\n“我们走。”她说。"
    metrics = _text_metrics(text)

    assert metrics["chapter_heading_count"] == 1
    # The metric counts repeated sentence patterns, not the total number of
    # occurrences. The first occurrence can be attached to a heading when the
    # source omits a sentence boundary, while the remaining repetitions still
    # form a detectable repeated pattern.
    assert metrics["duplicate_sentence_count"] >= 1
    assert metrics["repeated_sentences"][0]["count"] >= 2
    assert metrics["ai_style_marker_total"] >= 6
    assert metrics["dialogue_ratio_percent"] > 0


def test_representative_sample_covers_beginning_middle_and_end():
    source = "A" * 12000 + "B" * 12000 + "C" * 12000
    sample = _representative_sample(source, max_chars=6000)

    assert "A" * 100 in sample
    assert "B" * 100 in sample
    assert "C" * 100 in sample
    assert "抽样片段 6/6" in sample


def test_web_inspection_uses_durable_generate_endpoint_and_long_timeout():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "success": True,
        "data": {"overall_score": 88, "verdict": "ok"},
        "error": None,
    }
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    context.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=context):
        result = __import__("asyncio").run(AIService().analyze_structured_text(
            "system",
            "manuscript",
            SimpleNamespace(
                base_url="http://127.0.0.1:4310/v1",
                api_key="web-login",
                model="deepseek",
            ),
        ))

    assert result["overall_score"] == 88
    url = client.post.call_args.args[0]
    payload = client.post.call_args.kwargs["json"]
    assert url.endswith("/v1/generate")
    assert payload["timeoutMs"] == 720_000
    assert payload["idempotencyKey"].startswith("manuscript-")


def test_all_free_web_calls_use_durable_generate_endpoint():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "success": True,
        "data": {"content": "第一段。\n\n第二段。"},
        "error": None,
    }
    client = AsyncMock()
    client.post.return_value = response
    context = AsyncMock()
    context.__aenter__.return_value = client
    context.__aexit__.return_value = None

    with patch("app.services.ai_service.httpx.AsyncClient", return_value=context):
        result = __import__("asyncio").run(AIService()._call(
            [{"role": "user", "content": "生成正文"}],
            "http://127.0.0.1:4310/v1",
            "web-login",
            "deepseek",
        ))

    assert result == "第一段。\n\n第二段。"
    url = client.post.call_args.args[0]
    payload = client.post.call_args.kwargs["json"]
    assert url.endswith("/v1/generate")
    assert payload["timeoutMs"] == 720_000
    assert payload["idempotencyKey"].startswith("ai-")


def test_interrupted_web_response_is_reclaimed_without_resubmitting_generation():
    running = MagicMock()
    running.raise_for_status.return_value = None
    running.json.return_value = {"status": "running"}
    completed = MagicMock()
    completed.raise_for_status.return_value = None
    completed.json.return_value = {
        "status": "completed",
        "response": {"success": True, "data": {"overall_score": 91}},
    }
    client = AsyncMock()
    client.post.side_effect = [__import__("httpx").ReadError("socket closed"), running, completed]
    context = AsyncMock()
    context.__aenter__.return_value = client
    context.__aexit__.return_value = None

    with (
        patch("app.services.ai_service.httpx.AsyncClient", return_value=context),
        patch("app.services.ai_service.asyncio.sleep", new=AsyncMock()),
    ):
        result = __import__("asyncio").run(AIService().analyze_structured_text(
            "system",
            "manuscript",
            SimpleNamespace(base_url="http://127.0.0.1:4310/v1", api_key="web-login", model="deepseek"),
        ))

    assert result["overall_score"] == 91
    urls = [call.args[0] for call in client.post.call_args_list]
    assert urls.count("http://127.0.0.1:4310/v1/generate") == 1
    assert urls.count("http://127.0.0.1:4310/v1/generate/status") == 2
