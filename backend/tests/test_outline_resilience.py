import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.ai_service import AIService
from app.services.novel_generate_service import _normalize_outline_chapters


def test_parse_json_response_accepts_fences_prefix_and_trailing_commas():
    service = AIService()
    raw = """审核结果如下：
```json
{"approved": true, "issues": [], "revised_chapters": [],}
```"""

    parsed = service._parse_json_response(raw, "outline audit")

    assert parsed["approved"] is True
    assert parsed["issues"] == []


def test_outline_audit_retries_invalid_json_once():
    service = AIService()
    service._call = AsyncMock(
        side_effect=[
            "这不是 JSON",
            json.dumps(
                {
                    "approved": True,
                    "issues": [],
                    "revised_chapters": [],
                }
            ),
        ]
    )

    result = asyncio.run(
        service.audit_outline_candidate(
            synopsis="梗概",
            roadmap={},
            state_ledger={},
            canon_facts=[],
            previous_chapters=[],
            candidate_chapters=[
                {"chapter_number": 6, "title": "第六章", "synopsis": "推进主线"}
            ],
            ai_config=SimpleNamespace(
                base_url="https://example.com",
                api_key="key",
                model="model",
            ),
        )
    )

    assert result["approved"] is True
    assert service._call.await_count == 2


def test_audit_revision_cannot_drop_required_outline_fields():
    original = [
        {
            "chapter_number": 6,
            "title": "进入楼市",
            "synopsis": "主角从股市获利后购买第一套房产。",
            "stage_id": "S2",
        },
        {
            "chapter_number": 7,
            "title": "判断地段",
            "synopsis": "主角调查城市发展方向。",
            "stage_id": "S2",
        },
    ]
    incomplete_revision = [
        {
            "chapter_number": 6,
            "transition": "承接上一阶段资产积累",
        }
    ]

    normalized = _normalize_outline_chapters(original, incomplete_revision)

    assert len(normalized) == 2
    assert normalized[0]["title"] == "进入楼市"
    assert normalized[0]["synopsis"] == "主角从股市获利后购买第一套房产。"
    assert normalized[0]["transition"] == "承接上一阶段资产积累"
    assert normalized[1]["title"] == "判断地段"
