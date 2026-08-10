import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.novel_generate import GenerateChapterRequest
from app.services.ai_service import ai_service
from app.services.novel_generate_service import (
    NovelGenerateService,
    _cross_segment_issues,
    _is_valid_standard_segment,
    _ledger_cash_reconciliation_issues,
    _local_chapter_issues,
    _normalize_standard_segment,
    _outline_preflight_issues,
    _chapter_review_required_detail,
    _rollback_facts_for_regeneration,
    _rollback_ledger_for_regeneration,
)


def issue_types(content, synopsis, ledger=None):
    return {
        item["type"]
        for item in _local_chapter_issues(
            content,
            {"synopsis": synopsis},
            ledger or {"time_place": "1993年深圳"},
        )
    }


def test_rejects_empty_account_then_unexplained_sale():
    content = "甲" * 4300 + "他确认目前空仓。第二天填单卖出三只股票，全部脱手。"
    assert "holding_flow" in issue_types(content, "比赛账户继续交易")


def test_review_required_payload_contains_candidate_and_exact_highlight():
    content = "陈远核对订单。随后他明确空仓，却在没有买入的情况下卖出股票。章末回到工厂。"
    detail = _chapter_review_required_detail(
        "正文校验未通过",
        content,
        [{
            "type": "holding_flow",
            "evidence": "没有买入的情况下卖出股票",
            "conflict_with": "持仓已经清空",
            "repair_instruction": "先写明合法买入及成交凭证，再安排卖出",
        }],
    )
    assert detail["code"] == "CHAPTER_REVIEW_REQUIRED"
    assert detail["candidate_content"] == content
    assert detail["actions"] == ["manual_edit", "regenerate"]
    match = detail["issues"][0]["matches"][0]
    assert content[match["start"]:match["end"]] == match["text"]

    paraphrased = _chapter_review_required_detail(
        "正文校验未通过",
        "他听说深圳物业准备再次挂牌，立刻赶去询问。",
        [{"evidence": "正文把已挂牌的深圳物业写成待挂牌公司"}],
    )
    assert paraphrased["issues"][0]["matches"][0]["text"] == "深圳物业"


def test_rejects_oversized_competition_account_and_unauthorized_credit():
    content = (
        "甲" * 4300
        + "第一名满仓八十万元。方立诚作为营业部副经理，当场特批一百万元低息融资。"
    )
    types = issue_types(content, "复赛统一本金5万元，不使用杠杆")
    assert "competition_capital" in types
    assert "authority_and_credit" in types


def test_rejects_known_historical_company_relisting_and_meta_leak():
    content = (
        "甲" * 4300
        + "第18章核查结束后，深圳物业准备改制，出售原始股并准备挂牌。"
    )
    types = issue_types(content, "1993年寻找投资项目")
    assert "historical_company" in types
    assert "meta_leak" in types


def test_outline_preflight_blocks_before_ai_spend():
    issues = _outline_preflight_issues(
        {
            "synopsis": (
                "1993年深圳物业准备改制，两个月后挂牌。"
                "主角自有30万、借款30万共60万，认购60万后自有资金剩10万。"
            )
        },
        {"time_place": "1993年深圳"},
    )
    types = {item["type"] for item in issues}
    assert "outline_historical_company" in types
    assert "outline_wealth_math" in types


def test_economy_mode_always_semantically_audits_and_extracts_actual_state(tmp_path, monkeypatch):
    monkeypatch.setenv("MINITEXT_DATA_DIR", str(tmp_path))
    db = AsyncMock()
    service = NovelGenerateService(db)
    chapter = SimpleNamespace(
        id=30, novel_id=2, chapter_number=2, title="守住本金", synopsis="主角完成一笔合法交易"
    )
    novel = SimpleNamespace(
        id=2, title="测试小说", genre="都市", synopsis="1993年创业",
        total_chapters=10, owner_id=9, ai_config_id=None, system_prompt=None,
        outline=json.dumps({"chapters": [{"chapter_number": 2, "title": "守住本金", "synopsis": "合法交易"}]}, ensure_ascii=False),
        story_roadmap=json.dumps({"total_chapters": 10, "stages": [{"id": "S1", "start_chapter": 1, "end_chapter": 10}]}, ensure_ascii=False),
        state_ledger=json.dumps({"current_chapter": 1, "time_place": "1993年深圳", "protagonist": {"name": "陈阳", "cash": "1000元"}}, ensure_ascii=False),
        canon_facts="[]", continuity_audits="[]", knowledge_graph=None,
    )
    service.chapter_repo.get = AsyncMock(return_value=chapter)
    service.chapter_repo.get_by_number = AsyncMock(return_value=None)
    service.novel_repo.get_by_id_and_owner = AsyncMock(return_value=novel)
    service.novel_repo.update = AsyncMock(return_value=novel)
    service.ai_config_repo.get_default = AsyncMock(return_value=SimpleNamespace(model="deepseek-v4-flash"))
    service.content_repo.get_latest = AsyncMock(return_value=None)
    service.content_repo.create = AsyncMock(return_value=SimpleNamespace(id=88))
    generated = "陈阳按公开信息完成交易。" + "正文" * 2199 + "。"
    audit = AsyncMock(return_value={"approved": True, "issues": [], "summary": "通过"})
    extract = AsyncMock(return_value={
        "state_ledger": {"current_chapter": 2, "time_place": "1993年深圳", "protagonist": {"name": "陈阳", "cash": "1100元"}},
        "new_irreversible_facts": [{"chapter": 2, "type": "wealth", "fact": "陈阳现金1100元", "cause": "正文"}],
    })
    with (
        patch.object(ai_service, "generate_chapter", AsyncMock(return_value=generated)),
        patch.object(ai_service, "audit_chapter_candidate", audit),
        patch.object(ai_service, "extract_canon_update", extract),
    ):
        asyncio.run(service.generate_chapter_content(
            chapter_id=30,
            req=GenerateChapterRequest(economy_mode=True),
            owner_id=9,
        ))
    audit.assert_awaited_once()
    extract.assert_awaited_once()
    service.content_repo.create.assert_awaited_once()
    db.commit.assert_awaited_once()


def test_spoken_rebirth_secret_is_blocked_but_inner_narration_is_allowed():
    spoken = (
        "周建军问他依据。陈远回答：“前世记忆告诉我下个月会暴涨。”"
        + "正文" * 2200
    )
    narration = (
        "陈远想起前世记忆，却只对周建军说：“成交量和追涨盘都在提醒我风险变大。”"
        + "正文" * 2200
    )
    assert "knowledge_boundary" in issue_types(
        spoken, "陈远根据公开行情控制风险"
    )
    assert "knowledge_boundary" not in issue_types(
        narration, "陈远根据公开行情控制风险"
    )


def test_rejects_long_truncated_segment_and_keeps_complete_prefix():
    truncated = "完整句。" + "未完成的长段落" * 180
    assert not _is_valid_standard_segment(truncated)
    normalized = _normalize_standard_segment("甲" * 900 + "。" + "未完成" * 100)
    assert normalized.endswith("。")
    assert _is_valid_standard_segment(normalized)


def test_rejects_unclosed_chapter_duplicate_scene_and_timeline_restart():
    paragraph = "陈远到营业部核对交割单，逐笔确认佣金、税费、回款和余额。" * 8
    content = (
        paragraph + "\n\n" + "过渡情节。" * 500 + "\n\n" + paragraph
        + "\n\n他走后，陈远又回到原来的柜台，重新核账。“这句话没有结束"
    )
    types = issue_types(content, "完成一次核账", {"protagonist": {"name": "陈远"}})
    assert "incomplete_chapter_ending" in types
    assert "unbalanced_delimiters" in types
    assert "duplicate_scene" in types
    assert "timeline_restart" in types


def test_rejects_meta_chapter_label_bad_subtraction_and_future_event():
    outline = {
        "synopsis": "本章只核账",
        "future_boundaries": [{
            "chapter_number": 30,
            "protected_events": ["注册远达制衣经营主体"],
        }],
    }
    content = (
        "叙事" * 2100
        + "第24章结束后的现金为25742.04元，扣除25.98元还剩25715.26元。"
        + "随后他注册远达制衣经营主体。"
    )
    types = {
        item["type"] for item in _local_chapter_issues(
            content, outline, {"protagonist": {"name": "陈远"}}
        )
    }
    assert "meta_chapter_reference" in types
    assert "wealth_subtraction" in types
    assert "future_stage_violation" in types


def test_cross_segment_duplicate_and_cash_reconciliation_are_blocked():
    repeated = "陈远逐笔核对交易费用和期末现金，确认每一项凭证。" * 30 + "。"
    assert "cross_segment_duplicate" in {
        item["type"] for item in _cross_segment_issues([
            repeated,
            "正常推进" * 300 + "。",
            repeated,
        ])
    }
    previous = {"protagonist": {"cash": "25742.04元"}}
    updated = {
        "protagonist": {"cash": "25715.26元"},
        "transaction_ledger": [
            {"chapter": 25, "type": "fee", "cash_change": -25.98, "evidence": "交割单"},
            {"chapter": 25, "type": "income", "cash_change": 120, "evidence": "稿费收据"},
        ],
    }
    assert _ledger_cash_reconciliation_issues(previous, updated, 25)


def test_regeneration_rollback_uses_snapshot_and_drops_current_facts():
    snapshot = {
        "current_chapter": 24,
        "protagonist": {"name": "陈远", "cash": "25742.04元"},
        "transaction_ledger": [{"chapter": 24, "type": "sale"}],
    }
    ledger = {
        "current_chapter": 25,
        "protagonist": {"name": "陈远", "cash": "25715.26元"},
        "transaction_ledger": [
            {"chapter": 24, "type": "sale"},
            {"chapter": 25, "type": "fee"},
        ],
        "generation_snapshots": {"25": snapshot},
    }
    restored = _rollback_ledger_for_regeneration(ledger, 25)
    assert restored["current_chapter"] == 24
    assert restored["protagonist"]["cash"] == "25742.04元"
    assert [item["chapter"] for item in restored["transaction_ledger"]] == [24]
    facts = [{"chapter": 24, "fact": "旧事实"}, {"chapter": 25, "fact": "待撤销"}]
    assert _rollback_facts_for_regeneration(facts, 25) == [facts[0]]


def test_legacy_regeneration_rollback_trims_chapter_histories():
    ledger = {
        "current_chapter": 25,
        "protagonist": {"name": "陈远", "cash": "错误余额"},
        "asset_accounts": [
            {"as_of_chapter": 24, "cash": "25742.04元", "assets": ["定期存单"], "debts": []},
            {"as_of_chapter": 25, "cash": "25715.26元", "assets": ["错误资产"], "debts": []},
        ],
        "timeline": [{"chapter": 24, "event": "清仓"}, {"chapter": 25, "event": "重复核账"}],
    }
    restored = _rollback_ledger_for_regeneration(ledger, 25)
    assert restored["current_chapter"] == 24
    assert restored["protagonist"]["cash"] == "25742.04元"
    assert restored["protagonist"]["assets"] == ["定期存单"]
    assert [item["chapter"] for item in restored["timeline"]] == [24]
