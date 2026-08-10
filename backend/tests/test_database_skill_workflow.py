import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.ai_service import AIService, ai_service
from app.services.novel_generate_service import (
    NovelGenerateService,
    _chapter_completion_issues,
    _load_standard_checkpoint_payload,
    _segments_for_issues,
    _validated_ai_audit_issues,
)
from app.schemas.novel_generate import GenerateChapterRequest


def test_regenerate_ignores_empty_later_content_rows_and_blocks_real_later_prose():
    """Blank outline chapters after the target must not cause an HTTP 500."""
    db = AsyncMock()
    service = NovelGenerateService(db)
    current = SimpleNamespace(id=25, novel_id=1, chapter_number=25)
    blank_later = SimpleNamespace(id=26, novel_id=1, chapter_number=26)
    written_later = SimpleNamespace(id=27, novel_id=1, chapter_number=27)

    service.chapter_repo.get = AsyncMock(return_value=current)
    service.chapter_repo.get_by_novel = AsyncMock(
        return_value=[current, blank_later, written_later]
    )
    service.novel_repo.get_by_id_and_owner = AsyncMock(
        return_value=SimpleNamespace(id=1)
    )
    service.content_repo.get_latest = AsyncMock(
        side_effect=[
            SimpleNamespace(content="existing chapter 25 prose"),
            None,
            SimpleNamespace(content="existing chapter 27 prose"),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            service.generate_chapter_content(
                chapter_id=25,
                req=GenerateChapterRequest(regenerate=True),
                owner_id=7,
            )
        )

    assert exc.value.status_code == 409
    assert service.content_repo.get_latest.await_count == 3


def test_story_roadmap_retries_until_ranges_cover_whole_book():
    service = AIService()
    invalid = {
        "total_chapters": 20,
        "protagonist": {"name": "陈阳", "identity": "工人", "initial_state": {}},
        "stages": [
            {
                "id": "S1",
                "name": "股市",
                "start_chapter": 1,
                "end_chapter": 5,
                "entry_condition": "重生",
                "exit_condition": "获得本金",
            }
        ],
    }
    valid = {
        "total_chapters": 20,
        "protagonist": {"name": "陈阳", "identity": "工人", "initial_state": {}},
        "stages": [
            {
                "id": "S1",
                "name": "股市",
                "start_chapter": 1,
                "end_chapter": 7,
                "entry_condition": "重生",
                "exit_condition": "获得本金",
            },
            {
                "id": "S2",
                "name": "楼市",
                "start_chapter": 8,
                "end_chapter": 14,
                "entry_condition": "配置资产",
                "exit_condition": "完成扩张",
            },
            {
                "id": "S3",
                "name": "互联网",
                "start_chapter": 15,
                "end_chapter": 20,
                "entry_condition": "发现网络机会",
                "exit_condition": "公司形成规模",
            },
        ],
    }
    service._call = AsyncMock(
        side_effect=[
            json.dumps(invalid, ensure_ascii=False),
            json.dumps(valid, ensure_ascii=False),
        ]
    )

    result = asyncio.run(
        service.generate_story_roadmap(
            title="重生1992",
            genre="都市",
            synopsis="主角经历股市、楼市、互联网造富",
            total_chapters=20,
            ai_config=SimpleNamespace(
                base_url="https://example.com",
                api_key="key",
                model="model",
            ),
        )
    )

    assert [stage["name"] for stage in result["stages"]] == ["股市", "楼市", "互联网"]
    assert service._call.await_count == 2


def test_standard_mode_keeps_checkpoint_when_deterministic_repair_still_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("MINITEXT_DATA_DIR", str(tmp_path))
    db = AsyncMock()
    service = NovelGenerateService(db)
    chapter = SimpleNamespace(
        id=10,
        novel_id=1,
        chapter_number=1,
        title="重生",
        synopsis="陈阳发现机会",
    )
    roadmap = {
        "total_chapters": 20,
        "stages": [
            {
                "id": "S1",
                "name": "股市",
                "start_chapter": 1,
                "end_chapter": 20,
                "entry_condition": "重生",
                "exit_condition": "完成积累",
            }
        ],
    }
    novel = SimpleNamespace(
        id=1,
        title="重生1992",
        genre="都市",
        synopsis="陈阳重生后创业",
        total_chapters=20,
        owner_id=7,
        ai_config_id=None,
        system_prompt=None,
        outline=json.dumps(
            {
                "chapters": [
                    {"chapter_number": 1, "title": "重生", "synopsis": "陈阳发现机会"}
                ]
            },
            ensure_ascii=False,
        ),
        story_roadmap=json.dumps(roadmap, ensure_ascii=False),
        state_ledger=json.dumps(
            {"current_chapter": 0, "protagonist": {"name": "陈阳", "cash": "100元"}},
            ensure_ascii=False,
        ),
        canon_facts="[]",
        continuity_audits="[]",
        knowledge_graph=None,
    )
    service.chapter_repo.get = AsyncMock(return_value=chapter)
    service.novel_repo.get_by_id_and_owner = AsyncMock(return_value=novel)
    service.ai_config_repo.get_default = AsyncMock(return_value=SimpleNamespace(model="deepseek-v4-pro"))
    service.content_repo.create = AsyncMock()

    passed_audit = {"approved": True, "issues": []}
    segments = ["甲" * 1099 + "。", "乙" * 1099 + "。", "丙" * 1099 + "。"]

    async def keep_segment(**kwargs):
        return kwargs["segment"]

    with (
        patch.object(ai_service, "generate_chapter_segment", AsyncMock(side_effect=segments)),
        patch.object(ai_service, "audit_chapter_candidate", AsyncMock(return_value=passed_audit)),
        patch.object(
            ai_service,
            "revise_chapter_segment",
            AsyncMock(side_effect=keep_segment),
        ),
        patch.object(
            ai_service,
            "revise_chapter_candidate",
            AsyncMock(return_value="终" * 7000 + "。"),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                service.generate_chapter_content(
                    chapter_id=10,
                    req=GenerateChapterRequest(),
                    owner_id=7,
                )
            )

    assert exc.value.status_code == 422
    service.content_repo.create.assert_not_awaited()
    db.commit.assert_not_awaited()
    checkpoint_path = tmp_path / "generation-checkpoints" / "chapter-10.json"
    assert checkpoint_path.exists()
    payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert payload["stage"] == "repair_retry_pending"
    assert len(payload["segments"]) == 0
    assert payload.get("approved_content") is None


def test_ai_audit_cannot_override_deterministic_length():
    content = "正文" * 2400 + "。"
    issues = _validated_ai_audit_issues([{
        "type": "length",
        "evidence": "正文共10512字",
        "conflict_with": "目标4500—5500字",
        "repair_instruction": "扩写或缩写",
    }], content)

    assert issues == []


def test_whole_chapter_gate_catches_restarted_scene_by_repeated_sentence():
    repeated = "你不是去深圳发财了？"
    content = (
        "陈远第一次进店询价。" + repeated
        + "他核对规格后离开，随后奔赴工厂处理合同。" * 6
        + "数日后，叙事却重新从同一次进店开始。" + repeated
        + "他再次递出同一张询价单。"
    )

    assert "duplicate_scene_sentence" in {
        item["type"] for item in _chapter_completion_issues(content)
    }


def test_checkpoint_self_heals_at_first_duplicate_segment(tmp_path, monkeypatch):
    monkeypatch.setenv("MINITEXT_DATA_DIR", str(tmp_path))
    fingerprint = "same-request"
    first = "甲" * 1099 + "。"
    duplicate = first
    third = "丙" * 1099 + "。"
    path = tmp_path / "generation-checkpoints" / "chapter-88.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({
        "fingerprint": fingerprint,
        "segments": [first, duplicate, third],
        "approved_content": "旧错误正文" * 900,
        "canon_update": {"bad": True},
    }, ensure_ascii=False), encoding="utf-8")

    payload = _load_standard_checkpoint_payload(88, fingerprint)

    assert payload["segments"] == [first]
    assert payload["stage"] == "checkpoint_self_healed"
    assert "approved_content" not in payload
    assert "canon_update" not in payload


def test_duplicate_issue_repairs_only_the_later_segment():
    segments = ["甲" * 1000 + "。", "乙" * 1000 + "。", "丙" * 1000 + "。"]
    issues = [{
        "type": "cross_segment_duplicate",
        "evidence": "第1段与第3段重复推进同一场景",
        "repair_instruction": "重写后一个重复段",
        "segments": [0, 2],
        "segment_index": 2,
    }]

    assert _segments_for_issues(segments, issues) == {2}


def test_standard_mode_segments_audits_and_extracts_ledger_from_prose(tmp_path, monkeypatch):
    monkeypatch.setenv("MINITEXT_DATA_DIR", str(tmp_path))
    db = AsyncMock()
    service = NovelGenerateService(db)
    chapter = SimpleNamespace(
        id=10,
        novel_id=1,
        chapter_number=1,
        title="第一桶金",
        synopsis="陈阳完成股票交易",
    )
    roadmap = {
        "total_chapters": 20,
        "stages": [
            {
                "id": "S1",
                "name": "股市",
                "start_chapter": 1,
                "end_chapter": 20,
                "entry_condition": "入市",
                "exit_condition": "获得本金",
            }
        ],
    }
    novel = SimpleNamespace(
        id=1,
        title="重生1992",
        genre="都市",
        synopsis="陈阳重生后创业",
        total_chapters=20,
        owner_id=7,
        ai_config_id=None,
        system_prompt=None,
        outline=json.dumps(
            {
                "chapters": [
                    {
                        "chapter_number": 1,
                        "title": "第一桶金",
                        "synopsis": "陈阳完成股票交易",
                        "stage_id": "S1",
                        "after_state": {"cash": "500万元"},
                        "irreversible_facts": ["陈阳拥有500万元"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        story_roadmap=json.dumps(roadmap, ensure_ascii=False),
        state_ledger=json.dumps(
            {"current_chapter": 0, "protagonist": {"name": "陈阳", "cash": "100元"}},
            ensure_ascii=False,
        ),
        canon_facts="[]",
        continuity_audits="[]",
        knowledge_graph=None,
    )
    service.chapter_repo.get = AsyncMock(return_value=chapter)
    service.novel_repo.get_by_id_and_owner = AsyncMock(return_value=novel)
    service.novel_repo.update = AsyncMock(return_value=novel)
    service.ai_config_repo.get_default = AsyncMock(return_value=SimpleNamespace(model="deepseek-v4-pro"))
    service.content_repo.get_latest = AsyncMock(return_value=None)
    service.content_repo.create = AsyncMock(
        return_value=SimpleNamespace(id=99, content="正文", word_count=2)
    )

    segment_generator = AsyncMock(
        side_effect=["甲" * 1599 + "。", "乙" * 1599 + "。", "丙" * 1599 + "。"]
    )
    canon_extractor = AsyncMock(return_value={
        "state_ledger": {
            "current_chapter": 1,
            "time_place": "1992年",
            # Deliberately wrong extracted snapshot. The deterministic gate
            # must use 100 + 420 and save 520 instead of trapping the user in
            # an endless checkpoint retry.
            "protagonist": {
                "name": "陈阳",
                "cash": "999元",
                "total_assets": "999元",
            },
            "transaction_ledger": [{
                "chapter": 1,
                "type": "income",
                "cash_change": 420,
                "counterparty": "客户",
                "evidence": "正文确认收入420元",
                "personal_cash_effect": True,
                "reconciled": True,
            }],
        },
        "new_irreversible_facts": [
            {"chapter": 1, "type": "wealth", "fact": "陈阳实际持有520元", "cause": "正文核算"}
        ],
    })
    semantic_audit = {
        "approved": False,
        "issues": [{
            "type": "role_boundary",
            "evidence": "陈阳提出推进交易",
            "conflict_with": "可能需要进一步审批",
            "repair_instruction": "补充审批边界",
        }],
    }

    async def keep_segment(**kwargs):
        return kwargs["segment"]

    with (
        patch.object(ai_service, "generate_chapter_segment", segment_generator),
        patch.object(
            ai_service,
            "audit_chapter_candidate",
            AsyncMock(return_value=semantic_audit),
        ),
        patch.object(
            ai_service,
            "revise_chapter_segment",
            AsyncMock(side_effect=keep_segment),
        ),
        patch.object(ai_service, "extract_canon_update", canon_extractor),
    ):
        result = asyncio.run(
            service.generate_chapter_content(
                chapter_id=10,
                req=GenerateChapterRequest(),
                owner_id=7,
            )
        )

    assert result.content_id == 99
    assert segment_generator.await_count == 3
    service.content_repo.create.assert_awaited_once()
    update_kwargs = service.novel_repo.update.await_args.kwargs
    assert json.loads(update_kwargs["state_ledger"])["protagonist"]["cash"] == "520元"
    saved_facts = json.loads(update_kwargs["canon_facts"])
    assert any("期末现金为520元" in item["fact"] for item in saved_facts)
    audits = json.loads(update_kwargs["continuity_audits"])
    assert audits[-1]["approved"] is True
    assert audits[-1]["warnings"][0]["type"] == "role_boundary"
    canon_extractor.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert not (tmp_path / "generation-checkpoints" / "chapter-10.json").exists()
