import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.services.knowledge_graph_service import (
    KnowledgeGraphService,
    _archive_payload,
    _filter_graph,
    _validate_archive_section,
)


def _novel():
    return SimpleNamespace(
        knowledge_graph=json.dumps({
            "characters": [
                {"name": "陈远", "role": "主角", "relations": [{"target": "Sam", "relation": "合作"}]},
                {"name": "Sam", "role": "客户", "relations": []},
            ],
            "events": [{"chapter": 8, "title": "收到订单"}],
        }, ensure_ascii=False),
        state_ledger=json.dumps({
            "current_chapter": 8,
            "time_place": "1992年深圳",
            "protagonist": {"name": "陈远", "cash": "210元"},
            "supporting_characters": [{"name": "Sam", "identity": "香港客户"}],
            "transaction_ledger": [{
                "chapter": 8,
                "type": "borrow",
                "cash_change": 4000,
                "counterparty": "Sam",
                "description": "借款",
            }],
            "item_custody": [{"chapter": 8, "item": "急单纸条", "holder": "陈远"}],
        }, ensure_ascii=False),
        canon_facts=json.dumps([
            {"chapter": 8, "type": "finance", "fact": "陈远欠Sam四千元"},
        ], ensure_ascii=False),
    )


def test_filter_graph_preserves_events_and_other_graph_fields():
    graph = {
        "characters": [{"name": "甲", "relations": []}],
        "events": [{"chapter": 1, "title": "开端"}],
        "layout": {"version": 1},
    }
    result = _filter_graph(graph)
    assert result["events"] == graph["events"]
    assert result["layout"] == {"version": 1}


def test_archive_payload_exposes_generation_authoritative_records():
    result = _archive_payload(_novel())
    assert result["current_chapter"] == 8
    assert result["transaction_ledger"][0]["cash_change"] == 4000
    assert result["item_custody"][0]["holder"] == "陈远"
    assert result["canon_facts"][0]["fact"] == "陈远欠Sam四千元"
    # Archive editing must not hide minor characters through display filtering.
    assert [item["name"] for item in result["characters"]] == ["陈远", "Sam"]


def test_archive_validation_rejects_invalid_or_blank_fact_data():
    with pytest.raises(HTTPException) as invalid_type:
        _validate_archive_section("transaction_ledger", {"amount": 1})
    assert invalid_type.value.status_code == 422

    with pytest.raises(HTTPException) as missing_fact:
        _validate_archive_section("canon_facts", [{"chapter": 1}])
    assert missing_fact.value.status_code == 422


def test_manual_archive_update_writes_authoritative_ledger_and_history():
    novel = _novel()
    db = AsyncMock()
    service = KnowledgeGraphService(db)
    service.novel_repo.get_by_id_and_owner = AsyncMock(return_value=novel)

    async def update(target, **values):
        for key, value in values.items():
            setattr(target, key, value)
        return target

    service.novel_repo.update = AsyncMock(side_effect=update)
    replacement = [{
        "chapter": 8,
        "type": "purchase",
        "amount": 28000,
        "cash_change": -28000,
        "counterparty": "深圳柜台商",
        "description": "采购芯片",
        "evidence": "第8章正文",
    }]

    result = asyncio.run(service.update_archive_section(
        novel_id=1,
        section="transaction_ledger",
        data=replacement,
        owner_id=7,
    ))

    stored = json.loads(novel.state_ledger)
    mirrored = json.loads(novel.knowledge_graph)["continuity"]
    assert stored["transaction_ledger"] == replacement
    assert mirrored["transaction_ledger"] == replacement
    assert stored["manual_edit_history"][-1]["section"] == "transaction_ledger"
    assert result["transaction_ledger"] == replacement
    db.commit.assert_awaited_once()
