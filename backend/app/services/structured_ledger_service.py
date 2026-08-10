"""Structured canonical ledger helpers for the Mintext backend.

This file is staged in the writable workspace and copied into the application
tree after review.  It intentionally uses JSON-compatible values only.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any


LEDGER_SCHEMA_VERSION = 2

_PROTAGONIST_DEFAULTS = {
    "name": "",
    "aliases": [],
    "identity": "",
    "career": "",
    "organization": "",
    "authority": [],
    "location": "",
    "current_goal": "",
    "wealth": "",
    "cash": "",
    "assets": [],
    "debts": [],
    "abilities": [],
    "reputation": "",
    "injuries": [],
    "relationships": [],
    "knowledge": [],
    "knowledge_limits": [],
    "items": [],
    "promises": [],
    "open_conflicts": [],
}

_SUPPORTING_DEFAULTS = {
    "name": "",
    "canonical_name": "",
    "aliases": [],
    "identity": "",
    "career": "",
    "organization": "",
    "authority": [],
    "location": "",
    "current_goal": "",
    "characteristics": "",
    "relationship_to_protagonist": "",
    "knowledge": [],
    "knowledge_limits": [],
    "items": [],
    "assets": [],
    "debts": [],
    "injuries": [],
    "status": "active",
    "last_seen_chapter": 0,
}

_DIALOGUE_DEFAULTS = {
    "canonical_name": "",
    "aliases": [],
    "languages": [],
    "forbidden_languages": [],
    "default_register": "",
    "speech_habits": [],
    "addresses": {},
    "address_history": [],
}


def _list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, (tuple, set)):
        return list(value)
    return [value]


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unique(values: Any) -> list:
    result: list = []
    seen: set[str] = set()
    for value in _list(values):
        if value in ("", None, [], {}):
            continue
        key = json.dumps(value, ensure_ascii=False, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _name_tokens(name: str) -> list[str]:
    name = _text(name)
    if not name:
        return []
    tokens = [name]
    for group in re.findall(r"[（(]([^）)]+)[）)]", name):
        tokens.extend(re.split(r"[/、,，]", group))
    base = re.sub(r"[（(].*?[）)]", "", name).strip()
    if base:
        tokens.append(base)
    return _unique([token.strip() for token in tokens if token.strip()])


def _merge_record(base: dict, incoming: dict, *, list_fields: set[str] | None = None) -> dict:
    result = deepcopy(base)
    list_fields = list_fields or set()
    for key, value in incoming.items():
        if value in ("", None, [], {}):
            continue
        if key in list_fields:
            result[key] = _unique([*_list(result.get(key)), *_list(value)])
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = {**result[key], **value}
        else:
            result[key] = deepcopy(value)
    return result


def _alias_map(protagonist: dict, supporting: list[dict], profiles: dict) -> dict[str, str]:
    aliases: dict[str, str] = {}
    records = [protagonist, *supporting]
    for record in records:
        canonical = _text(record.get("canonical_name") or record.get("name"))
        if not canonical:
            continue
        for alias in _unique([canonical, *_name_tokens(record.get("name", "")), *_list(record.get("aliases"))]):
            aliases[_text(alias)] = canonical
    for key, profile in profiles.items():
        canonical = _text(
            profile.get("canonical_name")
            or aliases.get(key)
            or re.sub(r"[（(].*?[）)]", "", key).strip()
            or key
        )
        for alias in _unique([key, canonical, *_name_tokens(key), *_list(profile.get("aliases"))]):
            aliases.setdefault(_text(alias), canonical)
    return aliases


def canonicalize_name(name: Any, aliases: dict[str, str]) -> str:
    text = _text(name)
    if not text:
        return ""
    if text in aliases:
        return aliases[text]
    base = re.sub(r"[（(].*?[）)]", "", text).strip()
    return aliases.get(base, text)


def normalize_canon_facts(facts: Any) -> list[dict]:
    """Deduplicate facts and attach lifecycle metadata without inventing facts."""
    result: list[dict] = []
    by_key: dict[tuple, int] = {}
    for raw in _list(facts):
        if not isinstance(raw, dict):
            raw = {"fact": _text(raw)}
        fact = _text(raw.get("fact"))
        if not fact:
            continue
        item = deepcopy(raw)
        item["chapter"] = int(item.get("chapter") or 0)
        item["type"] = _text(item.get("type") or "event")
        item["fact"] = fact
        item.setdefault(
            "fact_id",
            "F-"
            + hashlib.sha1(
                f"{item['chapter']}|{item['type']}|{fact}".encode("utf-8")
            ).hexdigest()[:12],
        )
        item.setdefault("status", "active")
        item.setdefault("effective_chapter", item["chapter"])
        item.setdefault("superseded_by", None)
        item.setdefault("entities", [])
        item.setdefault("evidence", _text(item.get("cause")))
        item.setdefault("importance", "normal")
        key = (item["chapter"], item["type"], re.sub(r"\s+", "", fact))
        if key in by_key:
            previous = result[by_key[key]]
            result[by_key[key]] = _merge_record(
                previous, item, list_fields={"entities"}
            )
        else:
            by_key[key] = len(result)
            result.append(item)
    return result


def normalize_state_ledger(
    ledger: Any,
    facts: Any = None,
    *,
    current_chapter: int | None = None,
) -> dict:
    """Upgrade legacy ledger JSON into the version-2 structured state."""
    source = deepcopy(_dict(ledger))
    protagonist = _merge_record(
        deepcopy(_PROTAGONIST_DEFAULTS),
        _dict(source.get("protagonist")),
        list_fields={
            "aliases", "authority", "assets", "debts", "abilities", "injuries",
            "relationships", "knowledge", "knowledge_limits", "items",
            "promises", "open_conflicts",
        },
    )
    protagonist["canonical_name"] = _text(
        protagonist.get("canonical_name")
        or re.sub(r"[（(].*?[）)]", "", protagonist.get("name", "")).strip()
        or protagonist.get("name")
    )
    protagonist["aliases"] = _unique(
        [*_list(protagonist.get("aliases")), *_name_tokens(protagonist.get("name", ""))]
    )

    profiles_source = _dict(source.get("dialogue_profiles"))
    supporting_raw = _list(source.get("supporting_characters"))
    initial_support: list[dict] = []
    for raw in supporting_raw:
        if not isinstance(raw, dict):
            raw = {"name": _text(raw)}
        record = _merge_record(
            deepcopy(_SUPPORTING_DEFAULTS),
            raw,
            list_fields={
                "aliases", "authority", "knowledge", "knowledge_limits", "items",
                "assets", "debts", "injuries",
            },
        )
        record["canonical_name"] = _text(
            record.get("canonical_name")
            or re.sub(r"[（(].*?[）)]", "", record.get("name", "")).strip()
            or record.get("name")
        )
        record["aliases"] = _unique(
            [*_list(record.get("aliases")), *_name_tokens(record.get("name", ""))]
        )
        initial_support.append(record)

    aliases = _alias_map(protagonist, initial_support, profiles_source)
    support_by_name: dict[str, dict] = {}
    for record in initial_support:
        canonical = canonicalize_name(record.get("canonical_name"), aliases)
        record["canonical_name"] = canonical
        record["name"] = canonical
        if canonical == protagonist.get("canonical_name"):
            continue
        support_by_name[canonical] = _merge_record(
            support_by_name.get(canonical, deepcopy(_SUPPORTING_DEFAULTS)),
            record,
            list_fields={
                "aliases", "authority", "knowledge", "knowledge_limits", "items",
                "assets", "debts", "injuries",
            },
        )
    supporting = list(support_by_name.values())
    aliases = _alias_map(protagonist, supporting, profiles_source)

    profiles: dict[str, dict] = {}
    for name, raw in profiles_source.items():
        raw = _dict(raw)
        canonical = canonicalize_name(raw.get("canonical_name") or name, aliases)
        profile = _merge_record(
            deepcopy(_DIALOGUE_DEFAULTS),
            raw,
            list_fields={
                "aliases", "languages", "forbidden_languages", "speech_habits",
                "address_history",
            },
        )
        profile["canonical_name"] = canonical
        profile["aliases"] = _unique(
            [*_list(profile.get("aliases")), *_name_tokens(name)]
        )
        addresses = {}
        for target, address in _dict(profile.get("addresses")).items():
            addresses[canonicalize_name(target, aliases)] = address
        profile["addresses"] = addresses
        profiles[canonical] = _merge_record(
            profiles.get(canonical, deepcopy(_DIALOGUE_DEFAULTS)),
            profile,
            list_fields={
                "aliases", "languages", "forbidden_languages", "speech_habits",
                "address_history",
            },
        )

    relationships: dict[tuple[str, str], dict] = {}
    for raw in _list(source.get("relationship_states")):
        if not isinstance(raw, dict):
            continue
        item = deepcopy(raw)
        a = canonicalize_name(item.get("character_a") or item.get("a"), aliases)
        b = canonicalize_name(item.get("character_b") or item.get("b"), aliases)
        if not a or not b:
            continue
        item["character_a"], item["character_b"] = a, b
        item.setdefault("status", "")
        item.setdefault("effective_chapter", 0)
        item.setdefault("reason", "")
        key = tuple(sorted((a, b)))
        previous = relationships.get(key)
        if previous is None or int(item.get("effective_chapter") or 0) >= int(previous.get("effective_chapter") or 0):
            relationships[key] = item

    normalized = {
        **source,
        "schema_version": LEDGER_SCHEMA_VERSION,
        "current_chapter": int(current_chapter if current_chapter is not None else source.get("current_chapter") or 0),
        "time_place": _text(source.get("time_place")),
        "protagonist": protagonist,
        "supporting_characters": supporting,
        "dialogue_profiles": profiles,
        "relationship_states": list(relationships.values()),
        "asset_accounts": _list(source.get("asset_accounts")),
        "transaction_ledger": _list(source.get("transaction_ledger")),
        "item_custody": _list(source.get("item_custody")),
        "timeline": _list(source.get("timeline")),
        "knowledge_boundaries": _list(source.get("knowledge_boundaries")),
        "commitments": _list(source.get("commitments") or source.get("promises")),
        "plot_threads": _list(source.get("plot_threads")),
        "migration_warnings": _unique(source.get("migration_warnings")),
    }

    # Preserve useful legacy state but mark unknown accounting provenance rather
    # than fabricating transactions for historical chapters.
    if not normalized["asset_accounts"] and (
        protagonist.get("cash") or protagonist.get("assets") or protagonist.get("debts")
    ):
        normalized["asset_accounts"] = [{
            "owner": protagonist.get("canonical_name"),
            "as_of_chapter": normalized["current_chapter"],
            "cash": protagonist.get("cash", ""),
            "assets": protagonist.get("assets", []),
            "debts": protagonist.get("debts", []),
            "source": "legacy_state_snapshot",
            "reconciled": False,
        }]
        normalized["migration_warnings"] = _unique([
            *normalized["migration_warnings"],
            "历史资产仅有余额快照，缺少逐笔流水；不得据此虚构收入或支出。",
        ])

    normalized["fact_summary"] = fact_summary(normalize_canon_facts(facts))
    return normalized


def merge_structured_history(previous: dict, updated: dict) -> dict:
    """Merge append-only histories so an AI snapshot cannot erase old records."""
    previous = _dict(previous)
    updated = _dict(updated)
    result = deepcopy(updated)
    keyed_fields = {
        # Amount is deliberately not part of the primary identity. The first
        # extraction may use cash_change while coverage repair uses amount for
        # the same evidenced transaction. Including amount created duplicate
        # fees and income records for one real-world event.
        "transaction_ledger": ("chapter", "type", "counterparty", "evidence"),
        "item_custody": ("item", "chapter", "transfer_chapter", "holder", "new_holder"),
        "timeline": ("chapter", "time", "origin", "destination", "location", "event"),
        "knowledge_boundaries": ("character", "chapter", "knowledge", "fact"),
        "commitments": ("id", "chapter", "owner", "content", "promise"),
        "plot_threads": ("id", "chapter", "thread", "content"),
    }
    for field, keys in keyed_fields.items():
        merged: list[dict] = []
        positions: dict[tuple, int] = {}
        for raw in [*_list(previous.get(field)), *_list(updated.get(field))]:
            if not isinstance(raw, dict):
                continue
            item = deepcopy(raw)
            key = tuple(_text(item.get(name)) for name in keys)
            if field == "transaction_ledger" and not _text(item.get("evidence")):
                key = (
                    _text(item.get("chapter")),
                    _text(item.get("type")),
                    _text(item.get("counterparty")),
                    _text(item.get("description")),
                    _text(item.get("amount") if item.get("amount") is not None else item.get("cash_change")),
                )
            if not any(key):
                key = (json.dumps(item, ensure_ascii=False, sort_keys=True),)
            if key in positions:
                merged[positions[key]] = _merge_record(merged[positions[key]], item)
            else:
                positions[key] = len(merged)
                merged.append(item)
        result[field] = merged

    # Asset accounts are current snapshots. Preserve owners absent from the
    # model response, while allowing the latest chapter snapshot to replace an
    # older snapshot for the same owner/account.
    accounts: dict[tuple[str, str], dict] = {}
    for raw in [*_list(previous.get("asset_accounts")), *_list(updated.get("asset_accounts"))]:
        if not isinstance(raw, dict):
            continue
        key = (_text(raw.get("owner")), _text(raw.get("account") or "total"))
        old = accounts.get(key)
        if old is None or int(raw.get("as_of_chapter") or 0) >= int(old.get("as_of_chapter") or 0):
            accounts[key] = deepcopy(raw)
    result["asset_accounts"] = list(accounts.values())
    return result


def apply_fact_status_updates(facts: list[dict], updates: Any) -> list[dict]:
    """Apply explicit lifecycle transitions by stable fact id."""
    normalized = normalize_canon_facts(facts)
    by_id = {fact["fact_id"]: fact for fact in normalized}
    allowed = {"active", "fulfilled", "failed", "superseded", "invalidated"}
    for raw in _list(updates):
        if not isinstance(raw, dict):
            continue
        fact = by_id.get(_text(raw.get("fact_id")))
        status = _text(raw.get("status"))
        if fact is None or status not in allowed:
            continue
        fact["status"] = status
        fact["superseded_by"] = raw.get("superseded_by")
        fact["status_reason"] = _text(raw.get("reason"))
        if raw.get("effective_chapter"):
            fact["status_effective_chapter"] = int(raw["effective_chapter"])
    return normalized


def fact_summary(facts: list[dict]) -> dict:
    active = [f for f in facts if f.get("status", "active") == "active"]
    counts: dict[str, int] = {}
    for fact in active:
        kind = _text(fact.get("type") or "event")
        counts[kind] = counts.get(kind, 0) + 1
    return {
        "active_count": len(active),
        "by_type": counts,
        "latest_chapter": max((int(f.get("chapter") or 0) for f in active), default=0),
    }


def relevant_canon_context(
    ledger: dict,
    facts: list[dict],
    chapter_outline: dict,
    *,
    max_facts: int = 160,
) -> dict:
    """Return compact but complete state plus facts relevant to the next chapter."""
    ledger = normalize_state_ledger(ledger, facts)
    facts = normalize_canon_facts(facts)
    outline_text = json.dumps(chapter_outline or {}, ensure_ascii=False)
    entities = {
        ledger.get("protagonist", {}).get("canonical_name", ""),
        *ledger.get("dialogue_profiles", {}).keys(),
    }
    mentioned = {name for name in entities if name and (name in outline_text or any(a in outline_text for a in _name_tokens(name)))}
    always_types = {
        "identity", "wealth", "asset", "item", "items", "relationship",
        "promise", "conflict", "injury", "dialogue_address",
    }

    scored: list[tuple[int, int, dict]] = []
    current = int(ledger.get("current_chapter") or 0)
    for index, fact in enumerate(facts):
        if fact.get("status", "active") != "active":
            continue
        text = json.dumps(fact, ensure_ascii=False)
        score = 0
        chapter = int(fact.get("chapter") or 0)
        if fact.get("type") in always_types:
            score += 5
        if any(name and name in text for name in mentioned):
            score += 8
        if chapter >= current - 3:
            score += 6
        elif chapter >= current - 10:
            score += 3
        if fact.get("importance") == "critical":
            score += 10
        scored.append((score, index, fact))

    selected = [item[2] for item in sorted(scored, key=lambda row: (row[0], row[1]), reverse=True)[:max_facts]]
    selected.sort(key=lambda item: (int(item.get("chapter") or 0), _text(item.get("type"))))

    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "current_state": ledger,
        "relevant_irreversible_facts": selected,
        "selection": {
            "total_active_facts": sum(1 for f in facts if f.get("status", "active") == "active"),
            "selected_facts": len(selected),
            "mentioned_entities": sorted(mentioned),
        },
    }


def structured_ledger_issues(ledger: dict) -> list[dict]:
    issues: list[dict] = []
    required = {
        "asset_accounts", "transaction_ledger", "item_custody", "timeline",
        "knowledge_boundaries", "commitments", "plot_threads",
    }
    missing = sorted(required - set(_dict(ledger)))
    if missing:
        issues.append({
            "type": "ledger_structure",
            "evidence": f"缺少结构化账本字段：{', '.join(missing)}",
            "repair_instruction": "重新提取完整的版本2状态账本。",
        })
    names = [_text(x.get("canonical_name") or x.get("name")) for x in _list(ledger.get("supporting_characters")) if isinstance(x, dict)]
    duplicates = sorted({name for name in names if name and names.count(name) > 1})
    if duplicates:
        issues.append({
            "type": "duplicate_character",
            "evidence": f"重复人物：{', '.join(duplicates)}",
            "repair_instruction": "按canonical_name和aliases合并人物。",
        })
    return issues


def canon_update_coverage_issues(
    previous: dict,
    updated: dict,
    content: str,
    chapter_number: int,
) -> list[dict]:
    """Ensure consequential prose changes were actually written to the ledger."""
    previous = _dict(previous)
    updated = _dict(updated)
    content = _text(content)
    issues: list[dict] = []

    def current_records(field: str) -> list[dict]:
        return [
            item for item in _list(updated.get(field))
            if isinstance(item, dict)
            and int(
                item.get("chapter")
                or item.get("effective_chapter")
                or item.get("acquired_chapter")
                or item.get("transfer_chapter")
                or 0
            ) == chapter_number
        ]

    financial = re.search(
        r"(买入|购入|卖出|出售|付款|支付|收入|回款|借款|贷款|还款|偿还|"
        r"投资|入股|分红|工资|奖金|佣金|手续费|花了|赚了|亏损|现金)",
        content,
    )
    if financial and not current_records("transaction_ledger"):
        issues.append({
            "type": "missing_transaction_ledger",
            "evidence": "正文发生资金或资产交易，但本章没有逐笔交易流水。",
            "repair_instruction": "从最终正文提取章初余额、每笔收支/借还/买卖、费用和章末余额；无法核算则拒绝保存。",
        })

    travel = re.search(
        r"(出发|抵达|赶到|前往|返回|离开|乘坐|坐上|搭乘|开车|乘车|火车|飞机|轮渡|出租车)",
        content,
    )
    if travel and not current_records("timeline"):
        issues.append({
            "type": "missing_timeline",
            "evidence": "正文发生跨地点移动，但本章时间地点/交通流水为空。",
            "repair_instruction": "记录出发地、目的地、交通方式、时间顺序、耗时和参与者。",
        })

    custody = re.search(
        r"(交给|递给|归还|取回|拿走|保管|寄存|托付|收到|领取).{0,20}"
        r"(钥匙|证件|合同|文件|纸条|账本|银行卡|现金|货物|样品|磁盘|相机|手机|物品)",
        content,
    )
    if custody and not current_records("item_custody"):
        issues.append({
            "type": "missing_item_custody",
            "evidence": "正文发生关键物品交接，但本章物品归属流水为空。",
            "repair_instruction": "记录物品、原持有人、新持有人、位置、状态和正文证据。",
        })

    commitment = re.search(
        r"(答应|承诺|约定|保证|必须在|截止|期限|欠下|受托|委托)",
        content,
    )
    if commitment and not current_records("commitments"):
        issues.append({
            "type": "missing_commitment",
            "evidence": "正文产生或结清承诺/期限，但本章承诺状态没有更新。",
            "repair_instruction": "记录责任人、对象、内容、期限及open/fulfilled/failed/superseded状态。",
        })

    # A newly extracted snapshot must never silently drop established durable
    # records.  Normalization usually preserves these, but this guard catches
    # malformed model output before persistence.
    for field in (
        "dialogue_profiles", "relationship_states", "asset_accounts",
        "transaction_ledger", "item_custody", "timeline",
        "knowledge_boundaries", "commitments", "plot_threads",
    ):
        old_value = previous.get(field)
        new_value = updated.get(field)
        if old_value and not new_value:
            issues.append({
                "type": "ledger_state_loss",
                "evidence": f"结构化账本字段 {field} 丢失了已有历史状态。",
                "repair_instruction": "保留既有有效记录，只追加、履约、失效或以可追踪方式替代。",
            })
    return issues
