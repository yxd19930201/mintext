import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.services.ai_service import AIService
from app.schemas.novel_generate import ChapterOutlineItem, OutlineResult
from app.services.novel_generate_service import (
    _align_outline_batch_numbers,
    _apply_dialogue_and_relationship_changes,
    _as_approved,
    _as_chapter_list,
    _as_issue_list,
    _normalize_outline_chapters,
    _preserve_stable_dialogue_state,
)


def test_later_outline_batch_numbers_are_owned_by_requested_interval():
    model_batch = [
        {
            "chapter_number": number,
            "title": f"模型第{number}章",
            "synopsis": f"第{number}项情节",
        }
        for number in range(1, 6)
    ]

    aligned = _align_outline_batch_numbers(model_batch, 6, 10)

    assert [item["chapter_number"] for item in aligned] == [6, 7, 8, 9, 10]
    assert aligned[0]["title"] == "模型第1章"


def test_incomplete_outline_batch_is_rejected_before_persistence():
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        _align_outline_batch_numbers(
            [{"chapter_number": 1, "title": "一", "synopsis": "一"}],
            6,
            10,
        )

    assert exc.value.status_code == 502
    assert "实际返回 1 章" in str(exc.value.detail)


def test_ai_call_retries_connect_failure_before_provider_accepts_request():
    service = AIService()
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "model": "test-model",
        "usage": {"prompt_tokens": 1, "completion_tokens": 2},
        "choices": [{"message": {"content": "恢复成功"}, "finish_reason": "stop"}],
    }
    client = AsyncMock()
    client.post.side_effect = [
        httpx.ConnectError("temporary dns failure", request=request),
        response,
    ]
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=client)
    context_manager.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.services.ai_service.httpx.AsyncClient", return_value=context_manager),
        patch("app.services.ai_service.asyncio.sleep", AsyncMock()) as sleep,
        patch("app.services.ai_service.ai_usage_service.record"),
    ):
        result = asyncio.run(service._call(
            [{"role": "user", "content": "test"}],
            "https://example.com/v1",
            "key",
            "test-model",
        ))

    assert result == "恢复成功"
    assert client.post.await_count == 2
    sleep.assert_awaited_once_with(2)


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


def test_outline_item_normalizes_common_ai_type_drift():
    item = ChapterOutlineItem.model_validate(
        {
            "chapter_number": "第 6 章",
            "title": {"text": "布局楼市"},
            "synopsis": ["承接股市获利", "购入第一套房"],
            "stage_id": 2,
            "before_state": "陈伟持有现金 1200 万元",
            "after_state": ["购入住宅", {"cash": "800 万元"}],
            "irreversible_facts": {
                "asset": "已购入第一套房",
                "time": "1998 年",
            },
            "transition": {"summary": "由证券收益转向不动产"},
            "speech_constraints": "Sam称陈远为陈生",
            "relationship_changes": "林晓月与陈远关系更加亲近",
            "address_changes": {
                "speaker": "林晓月",
                "target": "陈远",
                "new_address": "阿远",
            },
        }
    )

    assert item.chapter_number == 6
    assert item.title == "布局楼市"
    assert item.synopsis == "承接股市获利；购入第一套房"
    assert item.stage_id == "2"
    assert item.before_state == {"summary": "陈伟持有现金 1200 万元"}
    assert item.after_state["items"][0] == "购入住宅"
    assert item.irreversible_facts == ["asset：已购入第一套房", "time：1998 年"]
    assert item.transition == "由证券收益转向不动产"
    assert item.speech_constraints == ["Sam称陈远为陈生"]
    assert item.relationship_changes[0]["description"] == "林晓月与陈远关系更加亲近"
    assert item.address_changes[0]["new_address"] == "阿远"


def test_outline_collection_accepts_mapping_and_nested_payload():
    result = OutlineResult.model_validate(
        {
            "total_chapters": 2,
            "theme": {"summary": "时代创业"},
            "chapters": {
                "chapter_1": {
                    "chapter_number": "1",
                    "title": "起步",
                    "synopsis": "进入市场",
                },
                "chapter_2": {
                    "chapter_number": "第2章",
                    "title": "转折",
                    "synopsis": "切换赛道",
                },
            },
        }
    )

    assert result.theme == "时代创业"
    assert [chapter.chapter_number for chapter in result.chapters] == [1, 2]


def test_audit_helpers_accept_string_object_and_localized_booleans():
    assert _as_approved("通过") is True
    assert _as_approved("false") is False
    assert _as_issue_list("主角资产前后不一致") == [
        {"type": "continuity", "evidence": "主角资产前后不一致"}
    ]
    assert len(_as_chapter_list({"revised_chapters": [
        {"chapter_number": 1, "title": "标题", "synopsis": "简介"}
    ]})) == 1


def test_revision_with_string_state_and_string_chapter_number_is_merged():
    normalized = _normalize_outline_chapters(
        [{
            "chapter_number": 6,
            "title": "进入楼市",
            "synopsis": "购房。",
            "before_state": {"cash": "1200万"},
        }],
        [{
            "chapter_number": "第6章",
            "after_state": "购买第一套房后现金降至800万",
            "irreversible_facts": "第一套房已经成交",
        }],
    )

    assert normalized[0]["title"] == "进入楼市"
    assert normalized[0]["after_state"] == {"summary": "购买第一套房后现金降至800万"}
    assert normalized[0]["irreversible_facts"] == ["第一套房已经成交"]


def test_outline_generation_contract_requires_continuity_state_fields():
    service = AIService()
    service._call = AsyncMock(
        return_value=json.dumps({
            "total_chapters": 10,
            "theme": "创业",
            "chapters": [],
        })
    )

    asyncio.run(
        service._generate_chapters_range(
            title="测试",
            genre="都市",
            synopsis="主角依次经历股票、楼市与互联网创业。",
            total_chapters=10,
            start=1,
            end=5,
            theme="",
            sys_msg="system",
            base_url="https://example.com",
            api_key="key",
            model="model",
        )
    )

    prompt = service._call.await_args.args[0][1]["content"]
    assert '"before_state"' in prompt
    assert '"after_state"' in prompt
    assert '"irreversible_facts"' in prompt
    assert '"stage_id"' in prompt
    assert '"speech_constraints"' in prompt
    assert '"relationship_changes"' in prompt
    assert '"address_changes"' in prompt


def test_outline_revision_accepts_revised_chapters_key():
    service = AIService()
    service._call = AsyncMock(
        return_value=json.dumps({
            "revised_chapters": [{
                "chapter_number": 10,
                "title": "修正资产",
                "synopsis": "保持资金连续。",
            }]
        })
    )

    result = asyncio.run(
        service.revise_outline_candidate(
            synopsis="梗概",
            roadmap={},
            state_ledger={},
            canon_facts=[],
            previous_chapters=[],
            candidate_chapters=[],
            issues=["资产矛盾"],
            ai_config=SimpleNamespace(
                base_url="https://example.com",
                api_key="key",
                model="model",
            ),
        )
    )

    assert result[0]["chapter_number"] == 10


def test_transport_errors_never_have_blank_messages_or_claim_auto_retry():
    service = AIService()

    interrupted = service._transport_error_detail(httpx.ReadError(""))
    timed_out = service._transport_error_detail(httpx.ReadTimeout(""))
    unknown = service._transport_error_detail(RuntimeError(""))

    assert "AI_RESPONSE_INTERRUPTED" in interrupted
    assert "未自动重试" in interrupted
    assert "AI_RESPONSE_TIMEOUT" in timed_out
    assert "未自动重试" in timed_out
    assert unknown.startswith("AI_CALL_FAILED:RuntimeError:")
    assert unknown != "AI_CALL_FAILED:RuntimeError: "


def test_economy_ledger_versions_addresses_only_after_explicit_change():
    ledger = {
        "dialogue_profiles": {
            "林晓月": {
                "languages": ["普通话"],
                "forbidden_languages": ["粤语"],
                "default_register": "自然普通话",
                "addresses": {"陈远": "陈远"},
                "address_history": [],
            }
        },
        "relationship_states": [],
    }
    outline = {
        "relationship_changes": [{
            "character_a": "林晓月",
            "character_b": "陈远",
            "old_status": "朋友",
            "new_status": "恋人",
            "reason": "双方明确关系",
        }],
        "address_changes": [{
            "speaker": "林晓月",
            "target": "陈远",
            "old_address": "陈远",
            "new_address": "阿远",
            "reason": "关系确立",
        }],
    }

    updated = _apply_dialogue_and_relationship_changes(ledger, outline, 20)

    profile = updated["dialogue_profiles"]["林晓月"]
    assert profile["languages"] == ["普通话"]
    assert profile["forbidden_languages"] == ["粤语"]
    assert profile["addresses"]["陈远"] == "阿远"
    assert profile["address_history"][0]["old"] == "陈远"
    assert profile["address_history"][0]["new"] == "阿远"
    assert profile["address_history"][0]["effective_chapter"] == 20
    assert updated["relationship_states"][0]["effective_chapter"] == 20


def test_canon_update_cannot_overwrite_stable_address_without_explicit_change():
    previous = {
        "dialogue_profiles": {
            "陈志森（Sam陈）": {
                "canonical_name": "陈志森",
                "aliases": ["Sam", "Sam陈", "陈志森"],
                "languages": ["粤语", "普通话"],
                "addresses": {"陈远": "陈生"},
                "address_history": [],
            }
        },
        "relationship_states": [
            {
                "character_a": "陈远",
                "character_b": "陈志森（Sam陈）",
                "b_calls_a": "陈生",
            }
        ],
    }
    ai_update = {
        "current_chapter": 11,
        "dialogue_profiles": {
            "Sam陈": {
                "languages": ["普通话"],
                "addresses": {"陈远": "阿远"},
            }
        },
        "relationship_states": [
            {
                "character_a": "陈远",
                "character_b": "Sam陈",
                "b_calls_a": "阿远",
            }
        ],
    }

    result = _preserve_stable_dialogue_state(previous, ai_update, {}, 11)

    assert "Sam陈" not in result["dialogue_profiles"]
    profile = result["dialogue_profiles"]["陈志森（Sam陈）"]
    assert profile["addresses"]["陈远"] == "陈生"
    assert profile["aliases"] == ["Sam", "Sam陈", "陈志森"]
    assert result["relationship_states"][0]["b_calls_a"] == "陈生"
