from app.services.novel_generate_service import (
    _first_money,
    _invalidate_checkpoint_canon_update,
    _ledger_cash_reconciliation_issues,
    _local_chapter_issues,
    _normalize_current_chapter_cash_ownership,
    _repair_cash_snapshot_from_transactions,
    _save_standard_checkpoint,
)

import json


def test_money_parser_understands_chinese_units():
    assert _first_money("约15万元") == 150000
    assert _first_money("12.5万") == 125000
    assert _first_money("33,676.12元") == 33676.12


def test_company_settled_purchase_does_not_change_personal_cash():
    previous = {"protagonist": {"cash": "25676.12元"}}
    updated = {
        "protagonist": {"cash": "33676.12元"},
        "transaction_ledger": [
            {
                "chapter": 26,
                "type": "income",
                "cash_change": 8400,
                "evidence": "三笔服务费均已实际到账",
            },
            {
                "chapter": 26,
                "type": "expense",
                "cash_change": -400,
                "evidence": "个人支付交通、通信及验货费用400元",
            },
            {
                "chapter": 26,
                "type": "expense",
                "cash_change": -3400,
                "evidence": "货款全部经贸易部账目结算，个人分文未沾",
            },
        ],
    }

    normalized = _normalize_current_chapter_cash_ownership(updated, 26)

    assert normalized["transaction_ledger"][2]["cash_change"] == 0
    assert normalized["transaction_ledger"][2]["personal_cash_effect"] is False
    assert _ledger_cash_reconciliation_issues(previous, normalized, 26) == []


def test_unspecified_misc_income_is_rejected_before_canon_extraction():
    content = (
        "三笔服务费合计五百三十六元，交通费二百一十元。"
        "连同此前几笔零散协调收入，个人现金净增约八千元。"
    )

    issues = _local_chapter_issues(content, {}, {})

    assert any(item["type"] == "unitemized_personal_cash_flow" for item in issues)


def test_fully_itemized_personal_cash_flow_is_allowed():
    content = (
        "三笔服务费实际到账合计八千四百元，个人支付交通、通信及验货费用四百元。"
        "个人现金净增八千元。"
    )

    issues = _local_chapter_issues(content, {}, {})

    assert not any(item["type"] == "unitemized_personal_cash_flow" for item in issues)


def test_wrong_extracted_closing_cash_is_repaired_without_regenerating_prose():
    previous = {
        "protagonist": {
            "name": "陈远",
            "canonical_name": "陈远",
            "cash": "25676.12元",
        }
    }
    updated = {
        "protagonist": {
            "name": "陈远",
            "canonical_name": "陈远",
            "cash": "22000元",
            "total_assets": "150000元",
            "wealth": "活期及现金22000元；总资产150000元",
        },
        "transaction_ledger": [
            {"chapter": 26, "type": "income", "cash_change": 8400, "evidence": "服务费到账"},
            {"chapter": 26, "type": "expense", "cash_change": -400, "evidence": "个人费用"},
            {
                "chapter": 26,
                "type": "purchase",
                "cash_change": -3400,
                "evidence": "货款全部经贸易部账户结算，个人分文未沾",
            },
        ],
        "asset_accounts": [{
            "chapter": 26,
            "as_of_chapter": 26,
            "owner": "陈远",
            "cash": 22000,
            "total_assets": 150000,
        }],
    }

    repaired, changed = _repair_cash_snapshot_from_transactions(previous, updated, 26)

    assert changed is True
    assert repaired["protagonist"]["cash"] == "33676.12元"
    assert repaired["protagonist"]["total_assets"] == "161676.12元"
    assert repaired["transaction_ledger"][2]["cash_change"] == 0
    assert repaired["asset_accounts"][0]["cash"] == 33676.12
    assert repaired["last_reconciliation"]["net_cash_change"] == 8000
    assert _ledger_cash_reconciliation_issues(previous, repaired, 26) == []


def test_failed_canon_payload_is_removed_from_checkpoint(tmp_path, monkeypatch):
    monkeypatch.setenv("MINITEXT_DATA_DIR", str(tmp_path))
    segment = "甲" * 999 + "。"
    fingerprint = "fp"
    _save_standard_checkpoint(
        26,
        fingerprint,
        [segment],
        approved_content=segment,
        canon_update={"state_ledger": {"protagonist": {"cash": "错误"}}},
    )

    _invalidate_checkpoint_canon_update(
        26,
        fingerprint,
        [segment],
        segment,
        [{"type": "ledger_cash_reconciliation"}],
    )

    payload = json.loads(
        (tmp_path / "generation-checkpoints" / "chapter-26.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["approved_content"] == segment
    assert payload["canon_update"] is None
    assert payload["canon_attempts"] == 1
    assert payload["stage"] == "canon_retry_pending"
