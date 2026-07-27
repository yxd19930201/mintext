import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.ai_service import AIService, ai_service
from app.services.novel_generate_service import NovelGenerateService
from app.schemas.novel_generate import GenerateChapterRequest


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


def test_rejected_chapter_is_not_saved_after_three_repairs():
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
    service.ai_config_repo.get_default = AsyncMock(return_value=SimpleNamespace())
    service.content_repo.create = AsyncMock()

    failed_audit = {
        "approved": False,
        "issues": [
            {
                "type": "wealth",
                "evidence": "突然变穷",
                "conflict_with": "已有资产",
                "repair_instruction": "补足因果",
            }
        ],
    }
    with (
        patch.object(ai_service, "generate_chapter", AsyncMock(return_value="候选正文")),
        patch.object(ai_service, "audit_chapter_candidate", AsyncMock(return_value=failed_audit)),
        patch.object(ai_service, "revise_chapter_candidate", AsyncMock(return_value="返修正文")),
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


def test_approved_chapter_and_canon_ledger_are_saved_together():
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
    service.ai_config_repo.get_default = AsyncMock(return_value=SimpleNamespace())
    service.content_repo.get_latest = AsyncMock(return_value=None)
    service.content_repo.create = AsyncMock(
        return_value=SimpleNamespace(id=99, content="正文", word_count=2)
    )

    ledger = {
        "current_chapter": 1,
        "protagonist": {"name": "陈阳", "cash": "500万元"},
    }
    with (
        patch.object(ai_service, "generate_chapter", AsyncMock(return_value="审核通过的正文")),
        patch.object(
            ai_service,
            "audit_chapter_candidate",
            AsyncMock(return_value={"approved": True, "issues": [], "summary": "通过"}),
        ),
        patch.object(
            ai_service,
            "extract_canon_update",
            AsyncMock(
                return_value={
                    "state_ledger": ledger,
                    "new_irreversible_facts": [
                        {
                            "chapter": 1,
                            "type": "wealth",
                            "fact": "陈阳拥有500万元",
                            "cause": "股票获利",
                        }
                    ],
                }
            ),
        ),
    ):
        result = asyncio.run(
            service.generate_chapter_content(
                chapter_id=10,
                req=GenerateChapterRequest(),
                owner_id=7,
            )
        )

    assert result.content_id == 99
    service.content_repo.create.assert_awaited_once()
    update_kwargs = service.novel_repo.update.await_args.kwargs
    assert json.loads(update_kwargs["state_ledger"])["protagonist"]["cash"] == "500万元"
    assert json.loads(update_kwargs["canon_facts"])[0]["fact"] == "陈阳拥有500万元"
    db.commit.assert_awaited_once()
