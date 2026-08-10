from app.services.structured_ledger_service import (
    apply_fact_status_updates,
    canon_update_coverage_issues,
    merge_structured_history,
    normalize_canon_facts,
    normalize_state_ledger,
    relevant_canon_context,
    structured_ledger_issues,
)


def legacy_ledger():
    return {
        "current_chapter": 20,
        "time_place": "1992年深圳",
        "protagonist": {
            "name": "陈远",
            "cash": "5万元",
            "assets": ["电子元件库存"],
            "debts": [],
        },
        "supporting_characters": [
            {
                "name": "周建军（军哥）",
                "identity": "证券从业者",
                "characteristics": "谨慎",
                "relationship_to_protagonist": "朋友",
            },
            {
                "name": "周建军",
                "identity": "证券从业者",
                "location": "深圳",
            },
        ],
        "dialogue_profiles": {
            "周建军（军哥）": {
                "languages": ["普通话"],
                "addresses": {"陈远": "陈老弟"},
            },
            "周建军": {
                "speech_habits": ["说话谨慎"],
            },
        },
        "relationship_states": [
            {
                "character_a": "周建军",
                "character_b": "陈远",
                "status": "朋友",
                "effective_chapter": 3,
            },
            {
                "character_a": "周建军（军哥）",
                "character_b": "陈远",
                "status": "合作伙伴",
                "effective_chapter": 18,
            },
        ],
    }


def test_legacy_ledger_is_upgraded_without_inventing_transactions():
    ledger = normalize_state_ledger(legacy_ledger(), [], current_chapter=20)

    assert ledger["schema_version"] == 2
    assert len(ledger["supporting_characters"]) == 1
    assert ledger["supporting_characters"][0]["canonical_name"] == "周建军"
    assert ledger["supporting_characters"][0]["location"] == "深圳"
    assert len(ledger["dialogue_profiles"]) == 1
    assert ledger["dialogue_profiles"]["周建军"]["addresses"]["陈远"] == "陈老弟"
    assert len(ledger["relationship_states"]) == 1
    assert ledger["relationship_states"][0]["status"] == "合作伙伴"
    assert ledger["transaction_ledger"] == []
    assert ledger["asset_accounts"][0]["source"] == "legacy_state_snapshot"
    assert ledger["asset_accounts"][0]["reconciled"] is False
    assert ledger["migration_warnings"]


def test_fact_lifecycle_metadata_and_duplicates_are_normalized():
    facts = normalize_canon_facts([
        {"chapter": 2, "type": "identity", "fact": "陈远进入电子厂"},
        {"chapter": 2, "type": "identity", "fact": "陈远进入电子厂", "cause": "正文"},
    ])
    assert len(facts) == 1
    assert facts[0]["status"] == "active"
    assert facts[0]["effective_chapter"] == 2
    assert "entities" in facts[0]
    assert facts[0]["evidence"] == "正文"


def test_relevance_search_keeps_old_identity_and_current_entities():
    ledger = normalize_state_ledger(legacy_ledger(), [], current_chapter=150)
    facts = [
        {"chapter": 1, "type": "identity", "fact": "陈远来自2023年", "importance": "critical"},
    ]
    facts.extend(
        {"chapter": chapter, "type": "event", "fact": f"第{chapter}章普通事件"}
        for chapter in range(2, 151)
    )
    facts.append(
        {"chapter": 20, "type": "relationship", "fact": "周建军固定称呼陈远为陈老弟"}
    )
    context = relevant_canon_context(
        ledger,
        facts,
        {"chapter_number": 151, "synopsis": "周建军陪陈远处理交易"},
        max_facts=40,
    )
    selected = [item["fact"] for item in context["relevant_irreversible_facts"]]
    assert "陈远来自2023年" in selected
    assert "周建军固定称呼陈远为陈老弟" in selected


def test_complete_version_two_ledger_has_no_structure_issues():
    ledger = normalize_state_ledger(legacy_ledger(), [])
    assert structured_ledger_issues(ledger) == []


def test_financial_and_travel_changes_require_current_chapter_records():
    previous = normalize_state_ledger(legacy_ledger(), [], current_chapter=20)
    updated = normalize_state_ledger(previous, [], current_chapter=21)
    issues = canon_update_coverage_issues(
        previous,
        updated,
        "陈远从深圳乘车前往广州，支付车费50元，又借款2000元购入货物。",
        21,
    )
    kinds = {item["type"] for item in issues}
    assert "missing_transaction_ledger" in kinds
    assert "missing_timeline" in kinds


def test_current_chapter_records_satisfy_coverage_gate():
    previous = normalize_state_ledger(legacy_ledger(), [], current_chapter=20)
    updated = normalize_state_ledger(previous, [], current_chapter=21)
    updated["transaction_ledger"].append({
        "chapter": 21, "type": "expense", "amount": "50元", "evidence": "支付车费"
    })
    updated["timeline"].append({
        "chapter": 21, "origin": "深圳", "destination": "广州", "transport": "汽车"
    })
    assert canon_update_coverage_issues(
        previous,
        updated,
        "陈远从深圳乘车前往广州，并支付车费50元。",
        21,
    ) == []


def test_history_merge_cannot_drop_old_transactions():
    previous = normalize_state_ledger(legacy_ledger(), [], current_chapter=20)
    previous["transaction_ledger"] = [
        {"chapter": 20, "type": "income", "amount": "1000元", "evidence": "收到货款"}
    ]
    updated = normalize_state_ledger(legacy_ledger(), [], current_chapter=21)
    updated["transaction_ledger"] = [
        {"chapter": 21, "type": "expense", "amount": "100元", "evidence": "支付车费"}
    ]
    merged = merge_structured_history(previous, updated)
    assert [item["chapter"] for item in merged["transaction_ledger"]] == [20, 21]


def test_history_merge_deduplicates_amount_and_cash_change_variants():
    previous = normalize_state_ledger(legacy_ledger(), [], current_chapter=24)
    previous["transaction_ledger"] = [{
        "chapter": 25,
        "type": "fee_payment",
        "cash_change": -25.98,
        "counterparty": "证券公司",
        "evidence": "交割单费用合计25.98元",
    }]
    updated = normalize_state_ledger(legacy_ledger(), [], current_chapter=25)
    updated["transaction_ledger"] = [{
        "chapter": 25,
        "type": "fee_payment",
        "amount": 25.98,
        "counterparty": "证券公司",
        "evidence": "交割单费用合计25.98元",
    }]
    merged = merge_structured_history(previous, updated)
    records = [item for item in merged["transaction_ledger"] if item["chapter"] == 25]
    assert len(records) == 1
    assert records[0]["amount"] == 25.98
    assert records[0]["cash_change"] == -25.98


def test_fact_status_transition_keeps_history_but_deactivates_old_rule():
    facts = normalize_canon_facts([
        {"chapter": 9, "type": "promise", "fact": "陈远答应支付学费"}
    ])
    updated = apply_fact_status_updates(facts, [{
        "fact_id": facts[0]["fact_id"],
        "status": "fulfilled",
        "reason": "第10章已经支付",
        "effective_chapter": 10,
    }])
    assert len(updated) == 1
    assert updated[0]["status"] == "fulfilled"
    assert updated[0]["status_effective_chapter"] == 10
