import json
import logging
import hashlib
import os
import re
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.models.novel import Novel
from app.models.chapter import Chapter
from app.models.chapter_content import ChapterContent
from app.repositories.novel_repo import NovelRepository
from app.repositories.chapter_repo import ChapterRepository
from app.repositories.chapter_content_repo import ChapterContentRepository
from app.repositories.ai_config_repo import AIConfigRepository
from app.services.ai_service import ai_service, normalize_chapter_paragraphs
from app.services.generation_mode_service import resolve_generation_config
from app.services.novel_skill_service import novel_skill_prompt
from app.services.structured_ledger_service import (
    normalize_canon_facts,
    normalize_state_ledger,
    relevant_canon_context,
    canon_update_coverage_issues,
    merge_structured_history,
    apply_fact_status_updates,
    structured_ledger_issues,
)
from app.schemas.novel_generate import (
    GenerateNovelOutlineRequest,
    GenerateChapterRequest,
    BatchGenerateChaptersRequest,
    GenerateNextChapterRequest,
    OutlineResult,
    ChapterOutlineItem,
    GenerateChapterResult,
    BatchGenerateResult,
    GenerateNextChapterResult,
)

logger = logging.getLogger(__name__)

_LEDGER_CHAPTER_HISTORY_FIELDS = (
    "asset_accounts", "transaction_ledger", "item_custody", "timeline",
    "knowledge_boundaries", "commitments", "plot_threads",
)


def _entry_chapter(item: object) -> int:
    if not isinstance(item, dict):
        return -1
    for key in ("chapter", "effective_chapter", "as_of_chapter", "transfer_chapter"):
        try:
            value = int(item.get(key) or -1)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return -1


def _rollback_ledger_for_regeneration(ledger: dict, chapter_number: int) -> dict:
    """Return the canonical state immediately before ``chapter_number``.

    New generations keep a full pre-chapter snapshot.  Legacy projects do not
    have snapshots, so their append-only histories are trimmed conservatively
    and the most recent earlier asset snapshot is used when available.
    """
    source = deepcopy(ledger or {})
    snapshots = source.get("generation_snapshots")
    if isinstance(snapshots, dict) and isinstance(snapshots.get(str(chapter_number)), dict):
        restored = deepcopy(snapshots[str(chapter_number)])
        restored["generation_snapshots"] = {
            key: deepcopy(value)
            for key, value in snapshots.items()
            if str(key).isdigit() and int(key) < chapter_number
        }
        return restored

    for field in _LEDGER_CHAPTER_HISTORY_FIELDS:
        values = source.get(field)
        if isinstance(values, list):
            source[field] = [
                deepcopy(item) for item in values
                if _entry_chapter(item) < 0 or _entry_chapter(item) < chapter_number
            ]
    for field in ("relationship_states",):
        values = source.get(field)
        if isinstance(values, list):
            source[field] = [
                deepcopy(item) for item in values
                if _entry_chapter(item) < 0 or _entry_chapter(item) < chapter_number
            ]

    earlier_accounts = [
        item for item in source.get("asset_accounts", [])
        if isinstance(item, dict) and 0 <= _entry_chapter(item) < chapter_number
    ]
    if earlier_accounts:
        account = max(earlier_accounts, key=_entry_chapter)
        protagonist = source.setdefault("protagonist", {})
        if account.get("cash") not in (None, ""):
            protagonist["cash"] = deepcopy(account["cash"])
        if isinstance(account.get("assets"), list):
            protagonist["assets"] = deepcopy(account["assets"])
        if isinstance(account.get("debts"), list):
            protagonist["debts"] = deepcopy(account["debts"])

    source["current_chapter"] = max(chapter_number - 1, 0)
    source["generation_snapshots"] = {
        key: deepcopy(value)
        for key, value in (snapshots or {}).items()
        if str(key).isdigit() and int(key) < chapter_number
    } if isinstance(snapshots, dict) else {}
    return source


def _rollback_facts_for_regeneration(facts: list[dict], chapter_number: int) -> list[dict]:
    return [
        deepcopy(item) for item in facts
        if _entry_chapter(item) < 0 or _entry_chapter(item) < chapter_number
    ]

_SEGMENT_ENDINGS = "。！？!?……；;”’）》】」』"
_CHAPTER_ENDINGS = "。！？!?……”’）》】」』"


def _json_value(raw: str | None, default):
    if not raw:
        return default
    try:
        value = json.loads(raw)
        return value
    except (TypeError, json.JSONDecodeError):
        return default


def _audit_entry(
    kind: str,
    chapter_range: str,
    approved: bool,
    attempts: int,
    issues: list,
    warnings: list | None = None,
) -> dict:
    entry = {
        "kind": kind,
        "chapter_range": chapter_range,
        "approved": approved,
        "attempts": attempts,
        "issues": issues,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if warnings:
        entry["warnings"] = warnings
    return entry


def _as_chapter_list(value) -> list[dict]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nested = value.get("chapters") or value.get("revised_chapters")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        if "chapter_number" in value:
            return [value]
        return [item for item in value.values() if isinstance(item, dict)]
    return []


def _chapter_number(value):
    try:
        return ChapterOutlineItem.normalize_chapter_number(value)
    except (TypeError, ValueError):
        return None


def _as_issue_list(value) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        return [value]
    return [{"type": "continuity", "evidence": str(value)}]


def _as_approved(value) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "pass", "passed", "approved", "通过", "是"}
    if isinstance(value, (int, float)):
        return value == 1
    return False


def _validated_ai_audit_issues(value, content: str) -> list[dict]:
    """Normalize semantic review findings without treating AI guesses as facts.

    The semantic reviewer is useful for finding scenes worth revising, but it
    can hallucinate measurable facts (most often the chapter length) or phrase
    a suspicion as a contradiction.  Deterministic gates remain authoritative;
    these findings drive one bounded repair and then become review warnings.
    """
    actual_length = len((content or "").strip())
    normalized: list[dict] = []
    uncertainty_tokens = (
        "可能", "疑似", "似乎", "或许", "未必", "可能超", "推测",
        "may ", "might ", "possibly", "appears to",
    )
    for raw in _as_issue_list(value):
        issue = dict(raw) if isinstance(raw, dict) else {
            "type": "continuity",
            "evidence": str(raw),
        }
        issue_type = str(issue.get("type") or "continuity").strip().lower()
        evidence = str(issue.get("evidence") or "")
        conflict = str(issue.get("conflict_with") or "")
        combined = f"{evidence} {conflict}".lower()

        # Word count is fully deterministic.  Never spend another generation
        # because a reviewer claimed 10,512 characters for a 4,846-char draft.
        if issue_type in {"length", "word_count", "chapter_length"}:
            if 4200 <= actual_length <= 6200:
                continue
            issue["evidence"] = f"正文实际共{actual_length}字"
            issue["conflict_with"] = "正文目标为4500—5500字，允许少量浮动"

        issue["source"] = "ai_semantic_audit"
        issue["blocking"] = False
        if any(token in combined for token in uncertainty_tokens):
            issue["confidence"] = "advisory"
        else:
            issue["confidence"] = "reviewed"
        normalized.append(issue)
    return normalized


def _checkpoint_path(chapter_id: int) -> Path:
    data_dir = Path(os.getenv("MINITEXT_DATA_DIR", "."))
    return data_dir / "generation-checkpoints" / f"chapter-{chapter_id}.json"


def _checkpoint_fingerprint(chapter_id: int, prompt: str, context: str, model: str) -> str:
    value = f"{chapter_id}\0{model}\0{prompt}\0{context}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def _is_valid_standard_segment(value: object) -> bool:
    """A checkpoint segment must contain a usable, complete slice of prose."""
    if not isinstance(value, str):
        return False
    text = value.strip()
    if len(text) < 800 or len(text) > 2100:
        return False
    # A token-limited response can still satisfy the length range while ending
    # mid-sentence (for example just "方立").  Such content must never become
    # a reusable checkpoint segment.
    if text[-1] not in _SEGMENT_ENDINGS:
        return False
    if text.count("“") != text.count("”"):
        return False
    if text.count("「") != text.count("」") or text.count("『") != text.count("』"):
        return False
    return True


def _normalize_standard_segment(value: object) -> str:
    """Keep the largest complete prose prefix within the checkpoint bounds."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    sentence_ends = _SEGMENT_ENDINGS

    # If the provider wrote beyond the desired segment size, keep the last
    # complete sentence before the hard checkpoint ceiling.
    if len(text) > 2100:
        ceiling = text[:2100]
        cut = max(ceiling.rfind(mark) for mark in sentence_ends)
        if cut >= 800:
            text = ceiling[: cut + 1].strip()

    # Token ceilings often leave a short unfinished tail. Drop only that tail
    # and preserve the completed, already-paid prose instead of calling the
    # model three more times with identical limits.
    if text and text[-1] not in sentence_ends:
        cut = max(text.rfind(mark) for mark in sentence_ends)
        if cut >= 800:
            text = text[: cut + 1].strip()
        else:
            return ""
    return text


def _chapter_completion_issues(content: str) -> list[dict]:
    """Reject paid prose that is visibly truncated or structurally duplicated."""
    text = (content or "").strip()
    issues: list[dict] = []
    if not text or text[-1] not in _CHAPTER_ENDINGS:
        issues.append({
            "type": "incomplete_chapter_ending",
            "evidence": text[-120:] if text else "正文为空",
            "conflict_with": "完整章节必须以闭合句子或对白结束",
            "repair_instruction": "补全被截断的对白、动作和场景收束，不得保留半句话",
        })
    unbalanced = []
    for left, right in (("“", "”"), ("「", "」"), ("『", "』"), ("（", "）"), ("《", "》")):
        if text.count(left) != text.count(right):
            unbalanced.append(f"{left}{right}")
    if unbalanced:
        issues.append({
            "type": "unbalanced_delimiters",
            "evidence": "、".join(unbalanced),
            "conflict_with": "引号、括号和书名号必须完整闭合",
            "repair_instruction": "补齐或删除未闭合符号，并检查对应句子是否被截断",
        })
    paragraphs = [
        re.sub(r"\s+", "", item)
        for item in re.split(r"\n\s*\n", text)
        if len(item.strip()) >= 140
    ]
    for i, left in enumerate(paragraphs):
        for j in range(i + 1, len(paragraphs)):
            right = paragraphs[j]
            shorter = min(len(left), len(right))
            ratio = SequenceMatcher(None, left, right, autojunk=False).ratio()
            if left == right or (shorter >= 220 and ratio >= 0.72):
                issues.append({
                    "type": "duplicate_scene",
                    "evidence": f"第{i + 1}与第{j + 1}个长段落高度重复（相似度{ratio:.0%}）",
                    "conflict_with": "同一场景、核算或对话不得在同章重复执行",
                    "repair_instruction": "删除重复版本，只保留时间线正确、数字统一的一次叙述",
                })
                return issues
    # Whole-chapter rewrites can repeat the same visit or conversation using
    # slightly different surrounding prose.  An exact non-trivial sentence
    # repeated far apart is a deterministic restart signal even when no two
    # complete paragraphs reach the similarity threshold.
    sentences = [
        re.sub(r"\s+", "", item).strip("“”\"' ")
        for item in re.split(r"(?<=[。！？!?；;])", text)
    ]
    first_seen: dict[str, int] = {}
    for index, sentence in enumerate(sentences):
        if len(sentence) < 10:
            continue
        previous = first_seen.get(sentence)
        if previous is not None and index - previous >= 4:
            issues.append({
                "type": "duplicate_scene_sentence",
                "evidence": f"同一句在相隔场景中重复出现：{sentence[:80]}",
                "conflict_with": "同一拜访、问答或任务不得在同章重新开始",
                "repair_instruction": "删除后出现的重复场景，只保留时间线正确的一次叙述",
            })
            return issues
        first_seen.setdefault(sentence, index)
    return issues


def _cross_segment_issues(segments: list[str]) -> list[dict]:
    """Catch a retried segment that restarts an already completed scene."""
    issues: list[dict] = []
    for i in range(len(segments)):
        for j in range(i + 1, len(segments)):
            left = re.sub(r"\s+", "", segments[i])
            right = re.sub(r"\s+", "", segments[j])
            matcher = SequenceMatcher(None, left, right, autojunk=False)
            block = matcher.find_longest_match(0, len(left), 0, len(right))
            if block.size >= 140 or matcher.ratio() >= 0.48:
                issues.append({
                    "type": "cross_segment_duplicate",
                    "evidence": f"第{i + 1}段与第{j + 1}段重复推进同一场景",
                    "conflict_with": "分段只能向前续写，不能重启已经完成的行动",
                    "repair_instruction": "重写后一个重复段，从上一段最后动作继续并完成尚未发生的任务",
                    "segments": [i, j],
                    "segment_index": j,
                })
    return issues


def _candidate_segment_issues(
    segments: list[str],
    index: int,
    candidate: str,
) -> list[dict]:
    """Return only cross-segment conflicts involving a replacement candidate."""
    candidate_segments = list(segments)
    if index < len(candidate_segments):
        candidate_segments[index] = candidate
    else:
        candidate_segments.append(candidate)
        index = len(candidate_segments) - 1
    return [
        issue for issue in _cross_segment_issues(candidate_segments)
        if index in issue.get("segments", [])
    ]


def _first_money(value: object) -> float | None:
    match = re.search(
        r"(-?\d[\d,]*(?:\.\d+)?)\s*(亿|万|千)?(?:元|块)?",
        str(value or ""),
    )
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
        multiplier = {"亿": 100000000, "万": 10000, "千": 1000}.get(
            match.group(2), 1
        )
        return amount * multiplier
    except ValueError:
        return None


_COMPANY_CASH_FLOW_PATTERNS = (
    re.compile(
        r"(?:货款|定金|尾款|采购款).{0,48}(?:全部|均)?(?:经|由|通过).{0,18}"
        r"(?:贸易部|公司|工厂|厂里).{0,18}(?:账目|账户)?(?:结算|支付|收取|入账)"
    ),
    re.compile(r"个人(?:分文未沾|未垫付|没有垫付|未支付|没有支付|不经手|未经手)"),
)


def _is_company_cash_flow(item: dict) -> bool:
    """Return True when a ledger row explicitly belongs to a company account.

    The canon extractor occasionally turns a factory/company purchase mentioned
    in the prose into a protagonist expense.  Ownership language in the same
    evidence is authoritative: company-settled money must not change the
    protagonist's personal cash balance.
    """
    text = " ".join(
        str(item.get(key) or "")
        for key in ("description", "evidence", "counterparty", "note")
    )
    return any(pattern.search(text) for pattern in _COMPANY_CASH_FLOW_PATTERNS)


def _normalize_current_chapter_cash_ownership(
    ledger: dict, chapter_number: int
) -> dict:
    """Remove company cash movements from the protagonist's personal ledger."""
    normalized = deepcopy(ledger or {})
    rows = normalized.get("transaction_ledger")
    if not isinstance(rows, list):
        return normalized
    for row in rows:
        if not isinstance(row, dict) or _entry_chapter(row) != chapter_number:
            continue
        if not _is_company_cash_flow(row):
            continue
        row["cash_change"] = 0
        row["personal_cash_effect"] = False
        row["reconciled"] = True
        row["ownership_note"] = "公司/贸易部账户结算，不影响主角个人现金"
    return normalized


def _ledger_cash_reconciliation_issues(
    previous: dict, updated: dict, chapter_number: int
) -> list[dict]:
    """Reconcile numeric cash snapshots against this chapter's cash movements."""
    previous_cash = _first_money((previous.get("protagonist") or {}).get("cash"))
    updated_cash = _first_money((updated.get("protagonist") or {}).get("cash"))
    if previous_cash is None or updated_cash is None:
        return []
    movements: list[float] = []
    seen: set[tuple] = set()
    for item in updated.get("transaction_ledger", []):
        if not isinstance(item, dict) or int(item.get("chapter") or 0) != chapter_number:
            continue
        if item.get("personal_cash_effect") is False:
            continue
        change = item.get("cash_change")
        if isinstance(change, bool):
            continue
        if isinstance(change, str):
            parsed_change = _first_money(change)
            if parsed_change is None:
                continue
            change = parsed_change
        if not isinstance(change, (int, float)):
            continue
        key = (
            int(item.get("chapter") or 0),
            str(item.get("type") or ""),
            str(item.get("counterparty") or ""),
            re.sub(r"\s+", "", str(item.get("evidence") or item.get("description") or "")),
            round(float(change), 4),
        )
        if key in seen:
            continue
        seen.add(key)
        movements.append(float(change))
    if not movements:
        return []
    expected = round(previous_cash + sum(movements), 2)
    if abs(expected - updated_cash) <= 0.02:
        return []
    return [{
        "type": "ledger_cash_reconciliation",
        "evidence": (
            f"期初现金{previous_cash:.2f} + 本章现金变动{sum(movements):.2f} "
            f"= {expected:.2f}，账本却记录{updated_cash:.2f}"
        ),
        "conflict_with": "结构化现金流水必须与期末现金守恒",
        "repair_instruction": "依据去重后的逐笔流水修正期末现金和总资产，不得重复扣费或漏记收入",
    }]


def _format_money(value: float) -> str:
    """Return a stable human-readable RMB balance for the state ledger."""
    rounded = round(float(value), 2)
    if rounded.is_integer():
        return f"{int(rounded)}元"
    return f"{rounded:.2f}元"


def _replace_labelled_money(text: object, label: str, value: float) -> str:
    """Replace a labelled Arabic-number amount without touching other assets."""
    source = str(text or "")
    if not source:
        return source
    number = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    pattern = re.compile(
        rf"({re.escape(label)}\s*(?:约|为|共|合计|[:：])?\s*)"
        r"-?\d[\d,]*(?:\.\d+)?\s*元?"
    )
    return pattern.sub(rf"\g<1>{number}元", source, count=1)


def _repair_cash_snapshot_from_transactions(
    previous: dict, updated: dict, chapter_number: int
) -> tuple[dict, bool]:
    """Deterministically reconcile an extracted cash snapshot.

    Approved prose must not become permanently unusable merely because the
    model copied a wrong ending balance into the canon snapshot.  The previous
    saved balance plus the deduplicated, protagonist-owned transaction rows is
    authoritative.  This function only corrects the snapshot; it never invents
    an income or expense row.
    """
    repaired = _normalize_current_chapter_cash_ownership(updated, chapter_number)
    previous_cash = _first_money((previous.get("protagonist") or {}).get("cash"))
    current_cash = _first_money((repaired.get("protagonist") or {}).get("cash"))
    if previous_cash is None:
        return repaired, False

    movements: list[float] = []
    seen: set[tuple] = set()
    for item in repaired.get("transaction_ledger", []):
        if not isinstance(item, dict) or _entry_chapter(item) != chapter_number:
            continue
        if item.get("personal_cash_effect") is False:
            continue
        raw_change = item.get("cash_change")
        if isinstance(raw_change, bool):
            continue
        if isinstance(raw_change, (int, float)):
            change = float(raw_change)
        elif isinstance(raw_change, str) and _first_money(raw_change) is not None:
            change = float(_first_money(raw_change) or 0)
        else:
            continue
        key = (
            _entry_chapter(item),
            str(item.get("type") or ""),
            str(item.get("counterparty") or ""),
            re.sub(r"\s+", "", str(item.get("evidence") or item.get("description") or "")),
            round(change, 4),
        )
        if key in seen:
            continue
        seen.add(key)
        movements.append(change)
    if not movements:
        return repaired, False

    expected_cash = round(previous_cash + sum(movements), 2)
    if current_cash is not None and abs(expected_cash - current_cash) <= 0.02:
        return repaired, False

    protagonist = repaired.setdefault("protagonist", {})
    protagonist["cash"] = _format_money(expected_cash)
    correction = expected_cash - current_cash if current_cash is not None else 0.0

    current_total = _first_money(protagonist.get("total_assets"))
    corrected_total = None
    if current_total is not None and current_cash is not None:
        corrected_total = round(current_total + correction, 2)
        protagonist["total_assets"] = _format_money(corrected_total)

    wealth = protagonist.get("wealth")
    if wealth:
        wealth = _replace_labelled_money(wealth, "活期及现金", expected_cash)
        wealth = _replace_labelled_money(wealth, "现金", expected_cash)
        if corrected_total is not None:
            wealth = _replace_labelled_money(wealth, "总资产", corrected_total)
        protagonist["wealth"] = wealth

    owner = str(
        protagonist.get("canonical_name") or protagonist.get("name") or "主角"
    )
    accounts = repaired.setdefault("asset_accounts", [])
    if not isinstance(accounts, list):
        accounts = []
        repaired["asset_accounts"] = accounts
    current_accounts = [
        item for item in accounts
        if isinstance(item, dict)
        and int(item.get("as_of_chapter") or item.get("chapter") or 0) == chapter_number
        and str(item.get("owner") or item.get("entity") or owner) == owner
    ]
    if current_accounts:
        for account in current_accounts:
            old_account_cash = _first_money(account.get("cash"))
            account["cash"] = expected_cash
            if account.get("total_assets") is not None and old_account_cash is not None:
                old_total = _first_money(account.get("total_assets"))
                if old_total is not None:
                    account["total_assets"] = round(
                        old_total + expected_cash - old_account_cash, 2
                    )
            account["reconciled"] = True
            account["reconciliation_source"] = "deterministic_transaction_sum"
    else:
        accounts.append({
            "chapter": chapter_number,
            "as_of_chapter": chapter_number,
            "owner": owner,
            "type": "cash_snapshot",
            "cash": expected_cash,
            "assets": deepcopy(protagonist.get("assets", [])),
            "debts": deepcopy(protagonist.get("debts", [])),
            "source": "deterministic_transaction_sum",
            "reconciled": True,
        })

    repaired["last_reconciliation"] = {
        "chapter": chapter_number,
        "opening_cash": previous_cash,
        "net_cash_change": round(sum(movements), 2),
        "closing_cash": expected_cash,
        "method": "deduplicated_personal_transaction_sum",
    }
    return repaired, True


def _load_standard_checkpoint_payload(chapter_id: int, fingerprint: str) -> dict:
    path = _checkpoint_path(chapter_id)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("fingerprint") != fingerprint:
            return {"fingerprint": fingerprint, "segments": []}
        segments = payload.get("segments")
        if not isinstance(segments, list):
            segments = []
        valid: list[str] = []
        for item in segments:
            if not _is_valid_standard_segment(item):
                break
            normalized = item.strip()
            # Old builds could checkpoint a structurally valid segment that
            # restarted an earlier scene. Stop at the first polluted segment;
            # generation can safely resume from that exact boundary.
            if _cross_segment_issues([*valid, normalized]):
                break
            valid.append(normalized)
        if len(valid) != len(segments):
            payload.pop("approved_content", None)
            payload.pop("candidate_content", None)
            payload.pop("canon_update", None)
            payload["stage"] = "checkpoint_self_healed"
            payload["recovery_note"] = (
                f"检测到第{len(valid) + 1}段无效或重复，已回退到最后一个安全段"
            )
        payload["segments"] = valid
        return payload
    except (OSError, ValueError, TypeError):
        return {"fingerprint": fingerprint, "segments": []}


def _load_standard_checkpoint(chapter_id: int, fingerprint: str) -> list[str]:
    return _load_standard_checkpoint_payload(chapter_id, fingerprint)["segments"]


def _save_standard_checkpoint(
    chapter_id: int,
    fingerprint: str,
    segments: list[str],
    **stage_updates,
) -> None:
    path = _checkpoint_path(chapter_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    existing = _load_standard_checkpoint_payload(chapter_id, fingerprint)
    payload = {
        **existing,
        "format": "standard-generation-v2",
        "fingerprint": fingerprint,
        "segments": segments,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **stage_updates,
    }
    temp.write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    temp.replace(path)


def _invalidate_checkpoint_canon_update(
    chapter_id: int,
    fingerprint: str | None,
    segments: list[str],
    content: str,
    issues: list | None = None,
) -> None:
    """Keep approved prose but never reuse a canon payload that failed gates.

    Previously the invalid payload stayed in the checkpoint forever, so every
    click loaded exactly the same broken ledger and could never succeed.
    """
    if not fingerprint:
        return
    payload = _load_standard_checkpoint_payload(chapter_id, fingerprint)
    attempts = int(payload.get("canon_attempts") or 0) + 1
    _save_standard_checkpoint(
        chapter_id,
        fingerprint,
        segments,
        stage="canon_retry_pending",
        approved_content=content,
        canon_update=None,
        canon_attempts=attempts,
        last_canon_issues=issues or [],
    )


def _delete_standard_checkpoint(chapter_id: int) -> None:
    try:
        _checkpoint_path(chapter_id).unlink(missing_ok=True)
    except OSError:
        logger.warning("Failed to remove chapter generation checkpoint", exc_info=True)


def _story_year(chapter_outline: dict | None, state_ledger: dict | None) -> int | None:
    combined = json.dumps(
        {"outline": chapter_outline or {}, "ledger": state_ledger or {}},
        ensure_ascii=False,
    )
    years = [int(value) for value in re.findall(r"(19\d{2}|20\d{2})年", combined)]
    return max(years) if years else None


def _outline_preflight_issues(
    chapter_outline: dict | None,
    state_ledger: dict | None,
) -> list[dict]:
    """Reject a broken outline before spending tokens on prose."""
    outline_text = json.dumps(chapter_outline or {}, ensure_ascii=False)
    issues: list[dict] = []
    year = _story_year(chapter_outline, state_ledger)
    if year and year < 2010 and re.search(r"融资融券|借券做空|融券卖出", outline_text):
        issues.append({
            "type": "outline_historical_market_rule",
            "evidence": f"{year}年大纲出现融资融券或借券做空",
            "conflict_with": "中国证券市场制度时间线",
            "repair_instruction": "生成正文前先修改大纲，改为空仓、止损或合法现货交易",
        })
    if year and year >= 1992 and re.search(
        r"深圳物业.{0,60}(改制|原始股|两个月后挂牌|准备挂牌)", outline_text
    ):
        issues.append({
            "type": "outline_historical_company",
            "evidence": "深圳物业已于1992年挂牌，大纲却安排其再次改制或挂牌",
            "conflict_with": "真实公司上市时间",
            "repair_instruction": "更换为符合年份和投资者资格的项目，或使用正式公开发行",
        })
    if re.search(r"自有30万.{0,30}借款30万.{0,30}(?:总计|共)60万", outline_text) and re.search(
        r"认购60万.{0,40}自有资金剩(?:余)?10万", outline_text
    ):
        issues.append({
            "type": "outline_wealth_math",
            "evidence": "自有30万全部投入后仍声称剩余10万",
            "conflict_with": "资金恒等式",
            "repair_instruction": "重新计算期初现金、借款、投资额、余额和负债",
        })
    if "现实资金不参与" in outline_text and re.search(
        r"实盘|现实资金.{0,20}(买入|投入|建仓)", outline_text
    ):
        issues.append({
            "type": "outline_simulation_boundary",
            "evidence": "大纲同时规定现实资金不参与并安排实盘操作",
            "conflict_with": "模拟盘与现实账户边界",
            "repair_instruction": "在生成正文前统一大纲账户类型",
        })
    if re.search(r"(副经理|营业部经理).{0,80}(特批|批准).{0,20}(100万|一百万元)", outline_text):
        issues.append({
            "type": "outline_authority",
            "evidence": "营业部个人未经独立审批直接提供百万元融资",
            "conflict_with": "职位权限和信用审批流程",
            "repair_instruction": "删除融资，或补齐机构审批、担保、额度依据和风险约束",
        })
    return issues


def _local_chapter_issues(
    content: str,
    chapter_outline: dict | None = None,
    state_ledger: dict | None = None,
) -> list[dict]:
    """Deterministic safety gate. Semantic audit still runs in every mode."""
    issues: list[dict] = _chapter_completion_issues(content)
    length = len(content.strip())
    if length < 4200 or length > 6200:
        issues.append({
            "type": "length",
            "evidence": f"正文共{length}字",
            "conflict_with": "正文目标为4500—5500字，允许少量浮动",
            "repair_instruction": "将正文调整至4500—5500字，保留完整行动、因果、核算和承接",
        })
    leaked = [
        token
        for token in (
            "after_state", "before_state", "irreversible_facts", "大纲要求",
            "大纲目标", "状态账本", "不可逆事实", "作为AI", "上一章完成调查",
            "第18章核查", "不存在“已经寄出却", "不会在正文里",
        )
        if token in content
    ]
    if leaked:
        issues.append({
            "type": "meta_leak",
            "evidence": "、".join(leaked),
            "conflict_with": "小说正文不得暴露提示词、章节加工或账本过程",
            "repair_instruction": "删除元信息，将必要衔接改写成角色世界内的自然叙事",
        })
    chapter_labels = re.findall(r"第\s*\d+\s*章", content)
    if chapter_labels:
        issues.append({
            "type": "meta_chapter_reference",
            "evidence": "、".join(sorted(set(chapter_labels))[:5]),
            "conflict_with": "正文叙事不得用章节编号解释资金或衔接",
            "repair_instruction": "改为角色世界内的时间、事件或凭证描述，不得出现编辑章节标签",
        })
    outline_text = json.dumps(chapter_outline or {}, ensure_ascii=False)
    ledger_text = json.dumps(state_ledger or {}, ensure_ascii=False)
    if "现实资金不参与" in outline_text and re.search(
        r"实盘(账户|交易|买入|卖出|持仓|排名)|现实资金.{0,16}(投入|买入|建仓)",
        content,
    ):
        issues.append({
            "type": "simulation_real_money_conflict",
            "evidence": "大纲规定现实资金不参与，但正文出现实盘或现实资金建仓",
            "conflict_with": "本章大纲的模拟盘/现实资产边界",
            "repair_instruction": "删除全部现实交易，现实现金保持大纲指定余额",
        })
    if "初赛" in outline_text and "模拟" in outline_text and "实盘榜" in content:
        issues.append({
            "type": "competition_rule_conflict",
            "evidence": "正文出现实盘榜",
            "conflict_with": "初赛只统计模拟账户排名",
            "repair_instruction": "删除实盘榜及现实收益，只保留模拟账户排名",
        })
    year = _story_year(chapter_outline, state_ledger)
    if year and year < 2010 and re.search(
        r"融资融券|借券做空|融券卖出|证券公司.{0,12}借券", content
    ):
        issues.append({
            "type": "historical_market_rule",
            "evidence": f"故事时间为{year}年，正文却出现融资融券或借券做空",
            "conflict_with": "中国证券市场2010年才正式启动融资融券试点",
            "repair_instruction": "改为空仓回避、止损退出或合法现货交易",
        })
    if year and year < 1998 and "小灵通" in content:
        issues.append({
            "type": "historical_device",
            "evidence": f"{year}年出现小灵通",
            "conflict_with": "通信设备时代背景",
            "repair_instruction": "改为公用电话、固定电话或当时确实持有的设备",
        })
    if year and year >= 1992 and re.search(
        r"深圳物业.{0,80}(准备改制|原始股|两个月后挂牌|准备挂牌)", content
    ):
        issues.append({
            "type": "historical_company",
            "evidence": "正文把已于1992年挂牌的深圳物业写成待改制或待挂牌公司",
            "conflict_with": "真实公司历史",
            "repair_instruction": "删除该项目，使用符合年份、发行方式和投资资格的合法机会",
        })
    if re.search(r"手机响.{0,20}(前台|房间|旅社).{0,8}电话", content):
        issues.append({
            "type": "device_logic",
            "evidence": "手机与旅社固定电话被写成同一设备",
            "conflict_with": "通信设备和来电路径",
            "repair_instruction": "明确改为房间固定电话，或删除冲突描述",
        })
    match = re.search(
        r"(周[一二三四五六日天]).{0,40}停牌一天.{0,240}\1.{0,20}复牌",
        content,
        re.S,
    )
    if match:
        issues.append({
            "type": "timeline_conflict",
            "evidence": "同一星期日期既写停牌一天又写复牌",
            "conflict_with": "交易日时间线",
            "repair_instruction": "停牌一整天后只能在下一交易日或公告指定日期复牌",
        })
    # A character cannot sell holdings after explicitly becoming empty unless a
    # new purchase/position is shown first.
    empty_at = max(content.rfind("目前空仓"), content.rfind("完全空仓"), content.rfind("持仓0"))
    if empty_at >= 0:
        tail = content[empty_at:]
        sell = re.search(r"卖出|清仓|全部脱手", tail)
        buy = re.search(r"买入|建仓|重新建立仓位|持有.{0,12}股", tail)
        if sell and (not buy or sell.start() < buy.start()):
            issues.append({
                "type": "holding_flow",
                "evidence": "正文明确空仓后，在没有重新买入的情况下卖出股票",
                "conflict_with": "证券持仓守恒",
                "repair_instruction": "补充合法买入、数量和成本，或删除凭空卖出情节",
            })
    if re.search(r"(初始|统一|保证金|本金).{0,20}5万", outline_text + ledger_text):
        oversized = re.search(r"(满仓|比赛账户|参赛账户).{0,12}(八十万|80万|一百万|100万)", content)
        if oversized:
            issues.append({
                "type": "competition_capital",
                "evidence": oversized.group(0),
                "conflict_with": "比赛统一5万元本金且没有合法杠杆来源",
                "repair_instruction": "将所有参赛账户统一为规则本金，或明确同等合法融资规则",
            })
    if re.search(r"(副经理|方立诚|营业部经理).{0,120}(特批|批准).{0,20}(100万|一百万元)", content, re.S):
        issues.append({
            "type": "authority_and_credit",
            "evidence": "营业部个人现场提供百万元低息融资",
            "conflict_with": "角色权限、担保和信用审批流程",
            "repair_instruction": "删除该融资，或完整交代机构审批、抵押担保和额度依据",
        })
    # Reject explicit arithmetic equations that do not balance.
    for match in re.finditer(
        r"(\d+(?:\.\d+)?)\s*万?\s*[+＋]\s*(\d+(?:\.\d+)?)\s*万?\s*[=＝]\s*(\d+(?:\.\d+)?)\s*万",
        content,
    ):
        left, right, total = map(float, match.groups())
        if abs((left + right) - total) > 0.02:
            issues.append({
                "type": "wealth_equation",
                "evidence": match.group(0),
                "conflict_with": "资金加总不成立",
                "repair_instruction": "按期初资金、收入、支出、余额重新计算",
            })
    for match in re.finditer(
        r"(\d[\d,]*(?:\.\d+)?)\s*(?:元)?[^\d。；]{0,8}?(?:减去|扣除|[-－])\s*"
        r"(\d[\d,]*(?:\.\d+)?)\s*(?:元)?\s*(?:还剩|等于|=|＝)\s*"
        r"(\d[\d,]*(?:\.\d+)?)\s*元",
        content,
    ):
        left, deduction, result = (
            float(value.replace(",", "")) for value in match.groups()
        )
        if abs((left - deduction) - result) > 0.011:
            issues.append({
                "type": "wealth_subtraction",
                "evidence": match.group(0),
                "conflict_with": "资金减法不成立",
                "repair_instruction": "依据正式凭证统一费用合计、净回款、现金余额和总资产",
            })

    # A net-cash result may not be bridged by an unspecified historical or
    # miscellaneous receipt.  Such prose can look arithmetically plausible at
    # the ending balance while making the transaction ledger impossible to
    # reconcile (and used to trap an approved checkpoint in a retry loop).
    vague_cash_bridge = re.search(
        r"(?:连同|加上|包括).{0,32}(?:此前|之前|零散|其他|若干|未列明)"
        r".{0,24}(?:收入|进账|报酬|服务费|回款)",
        content,
    )
    net_cash_claim = re.search(
        r"(?:个人)?(?:现金|资金)?.{0,12}(?:净增|增加|净收入|净收益)",
        content,
    )
    if vague_cash_bridge and net_cash_claim:
        issues.append({
            "type": "unitemized_personal_cash_flow",
            "evidence": vague_cash_bridge.group(0),
            "conflict_with": "主角个人现金必须由本章逐笔已列收入和支出闭合",
            "repair_instruction": (
                "删除未列金额的此前/零散/其他收入；逐笔写明主角本人实际到账的全部收入和"
                "实际支付费用，使期初现金＋收入－支出＝期末现金。公司账户收支不得混入。"
            ),
        })

    financial_labels: dict[str, list[tuple[float, str]]] = {}
    for match in re.finditer(
        r"(总资产|活期(?:及|加)现金|交易费用(?:合计)?|净收益)"
        r".{0,18}?(\d[\d,]*(?:\.\d+)?)\s*元",
        content,
    ):
        label = re.sub(r"加|及|合计", "", match.group(1))
        value = float(match.group(2).replace(",", ""))
        context = content[max(0, match.start() - 35):match.end() + 35]
        financial_labels.setdefault(label, []).append((value, context))
    for label, records in financial_labels.items():
        values = {round(item[0], 2) for item in records}
        if len(values) <= 1:
            continue
        contexts = "；".join(item[1] for item in records[:3])
        if not re.search(r"扣除前|暂计|原有|此前|由.{0,12}(?:增至|降至)|核对前", contexts):
            issues.append({
                "type": "financial_value_conflict",
                "evidence": f"{label}出现多个未解释数值：{sorted(values)}",
                "conflict_with": "同一核算时点只能有一个期末金额",
                "repair_instruction": "统一核算时点；逐笔列出期初、收入、支出、内部转账和期末余额",
            })

    protagonist_name = str((state_ledger or {}).get("protagonist", {}).get("name") or "").strip()
    if protagonist_name and re.search(rf"他走后，\s*{re.escape(protagonist_name)}", content):
        issues.append({
            "type": "timeline_restart",
            "evidence": f"他走后，{protagonist_name}",
            "conflict_with": "角色离场后不能无过渡地回到同一场景",
            "repair_instruction": "删除重复场景，按唯一时间线继续后续行动",
        })

    for future in (chapter_outline or {}).get("future_boundaries", []):
        if not isinstance(future, dict):
            continue
        protected = [str(item) for item in future.get("protected_events", []) if str(item).strip()]
        hit = next((item for item in protected if item in content), None)
        if hit:
            issues.append({
                "type": "future_stage_violation",
                "evidence": hit,
                "conflict_with": f"该事件属于第{future.get('chapter_number')}章，当前章不得提前完成",
                "repair_instruction": "只保留调查、意向或准备，不得提前签约、付款、取得资产或完成结果",
            })
    # The protagonist's rebirth/foreknowledge is a private knowledge
    # boundary unless canon explicitly records a disclosure.  Inner narration
    # may mention it, but spoken dialogue may not leak it accidentally.
    dialogue_fragments = re.findall(r"[“\"]([^”\"]+)[”\"]", content)
    secret_patterns = re.compile(
        r"(前世记忆|前世发生|我重生|我是重生|来自未来|上辈子|上一世)"
    )
    leaked = [
        fragment for fragment in dialogue_fragments
        if secret_patterns.search(fragment)
    ]
    if leaked:
        issues.append({
            "type": "knowledge_boundary",
            "evidence": leaked[0][:160],
            "conflict_with": "重生与前世记忆仅主角本人知晓，未发生正式披露事件",
            "repair_instruction": (
                "将对白改为基于公开信息、现场迹象、经验或直觉的判断；"
                "前世记忆只能出现在主角内心叙述中。"
            ),
        })

    # Generic event state machine: a result may be booked only after the
    # execution and evidence phases. This applies to every amount, party and
    # chapter instead of matching one story-specific sentence.
    pending_execution = re.search(
        r"(尚未|还未|未能|没有|没)(?:.{0,12})"
        r"(付款|支付|购入|采购|找到|入库|到账|交付|验收|获批|取得凭证|形成货权)|"
        r"(明天|次日|随后|之后)(?:.{0,18})(付款|采购|找货|找料|入库|审批|验收)",
        content,
    )
    booked_result = re.search(
        r"(已经|已|立即|当即|直接|记为|确认为|转为)(?:.{0,24})"
        r"(资产|收入|借款|债务|货权|库存|回款|投资|应收款)",
        content,
    )
    completed_execution = re.search(
        r"(实际付款|完成支付|款项到账|购入并入库|验收入库|取得.{0,8}凭证|"
        r"客户确认.{0,24}(?:付款|入库)|供应商.{0,12}(?:收款|出具凭证))",
        content,
    )
    if (
        pending_execution
        and booked_result
        and booked_result.start() > pending_execution.start()
        and not (
            completed_execution
            and pending_execution.end() <= completed_execution.start() < booked_result.start()
        )
    ):
        issues.append({
            "type": "premature_asset_recognition",
            "evidence": f"{pending_execution.group(0)}；{booked_result.group(0)}",
            "conflict_with": "事件状态机缺少执行或结果凭证，状态却已提前入账",
            "repair_instruction": (
                "按意向、条件确认、实际执行、结果凭证、状态入账的顺序补齐；"
                "未执行的事项只能记录为承诺或待办"
            ),
        })

    conditional_deadline = re.search(
        r"交期从.{0,24}(?:到厂|到货|确认|生效|验收).{0,10}起算",
        content,
    )
    unconditional_deadline = re.search(
        r"(?:承诺|保证|确保|带话).{0,36}(?:\d+|[一二三四五六七八九十百]+)"
        r"(?:天|日)(?:内)?(?:交付|交货|交期)|"
        r"(?:\d+|[一二三四五六七八九十百]+)(?:天|日)交期.{0,20}(?:承诺|保证|包赔)",
        content,
    )
    if conditional_deadline and unconditional_deadline:
        window_start = min(conditional_deadline.start(), unconditional_deadline.start())
        window_end = max(conditional_deadline.end(), unconditional_deadline.end())
        terms = content[window_start:window_end]
        confirmed = re.search(r"(双方|客户|对方).{0,12}(书面)?确认|确认单|合同约定", terms)
    else:
        confirmed = None
    if conditional_deadline and unconditional_deadline and not confirmed:
        issues.append({
            "type": "delivery_term_conflict",
            "evidence": f"{conditional_deadline.group(0)}；{unconditional_deadline.group(0)}",
            "conflict_with": "合同交期必须有双方确认的唯一、明确起算点",
            "repair_instruction": "明确双方确认的唯一交期起算条件；未确认前只能说明预计周期",
        })

    invalid_late_clause = re.search(
        r"(?:超过|逾期).{0,8}(?:一天|1天).{0,18}(?:亲自验货|才验货)",
        content,
    )
    if invalid_late_clause:
        issues.append({
            "type": "invalid_delivery_liability",
            "evidence": invalid_late_clause.group(0),
            "conflict_with": "验货是交付前的质量义务，不是发生逾期后的补救措施",
            "repair_instruction": "把验货改为交付前必做；逾期责任另写加急运费、违约金或合同赔付",
        })

    delayed_receivable = re.search(
        r"(?:应收款|欠款).{0,12}(?:不用|不必|无需).{0,8}(?:急着|立即|继续).{0,8}(?:催|逼|收)",
        content,
    )
    if delayed_receivable:
        issues.append({
            "type": "receivable_collection_regression",
            "evidence": delayed_receivable.group(0),
            "conflict_with": "现金流困难且存在逾期应收款，新订单不能替代旧款催收",
            "repair_instruction": "改为按账龄持续分批催收，同时停止用降价换取拖欠客户的新订单",
        })

    return issues


def _segments_for_issues(segments: list[str], issues: list) -> set[int]:
    indexes: set[int] = set()
    for issue in issues:
        issue_type = str(issue.get("type") or "").lower()
        repair = str(issue.get("repair_instruction") or "")
        explicit_index = issue.get("segment_index")
        if isinstance(explicit_index, int) and 0 <= explicit_index < len(segments):
            indexes.add(explicit_index)
            continue
        evidence = str(issue.get("evidence") or "")
        segment_pair = re.search(r"第(\d+)段与第(\d+)段", evidence)
        if segment_pair:
            later = max(int(segment_pair.group(1)), int(segment_pair.group(2))) - 1
            if 0 <= later < len(segments):
                indexes.add(later)
                continue
        cross_segment_finance = any(
            token in issue_type
            for token in (
                "价格", "金额", "股数", "证券", "资产", "账本", "资金",
                "时间", "顺序", "price", "amount", "share", "asset",
                "ledger", "cash", "fund", "timeline", "sequence",
            )
        ) or any(
            token in repair
            for token in (
                "统一", "所有数字", "重新计算", "资金流向", "时间线",
                "单价", "股数", "总资产", "期末资产", "先后顺序",
            )
        )
        if issue_type == "length" or cross_segment_finance or any(
            token in repair
            for token in ("整章", "时间线", "顺序", "先完成", "再进入")
        ):
            indexes.update(range(len(segments)))
            continue
        fragments = [item.strip("“”\"' ：:，,。") for item in re.split(r"[；;\n]", evidence)]
        for index, segment in enumerate(segments):
            if any(len(fragment) >= 5 and fragment in segment for fragment in fragments):
                indexes.add(index)
    # An audit may describe a cross-segment inconsistency without quoting text.
    # Repair the final segment in that case because it owns result settlement.
    return indexes or ({len(segments) - 1} if segments else set())


def _review_issue_matches(content: str, issue: dict) -> list[dict]:
    """Locate quoted evidence so the desktop editor can mark it precisely.

    Reviewers do not always return a verbatim quote.  Prefer the complete
    evidence, then quoted/sentence fragments, and finally a distinctive part
    of the evidence.  Issues without a safe text match still remain visible in
    the modification list, but we never highlight an unrelated sentence.
    """
    evidence = str(issue.get("evidence") or "").strip()
    if not content or not evidence:
        return []

    candidates: list[str] = [evidence]
    candidates.extend(
        match.strip()
        for match in re.findall(r"[“\"']([^”\"']{4,240})[”\"']", evidence)
    )
    candidates.extend(
        item.strip("“”\"' ：:，,。；;\n\t")
        for item in re.split(r"[；;\n]|(?:。(?=\S))", evidence)
    )
    if "：" in evidence:
        candidates.append(evidence.split("：", 1)[1].strip())
    if ":" in evidence:
        candidates.append(evidence.split(":", 1)[1].strip())

    matches: list[dict] = []
    seen: set[tuple[int, int]] = set()
    for candidate in sorted(set(candidates), key=len, reverse=True):
        if len(candidate) < 4:
            continue
        start = content.find(candidate)
        if start < 0:
            continue
        end = start + len(candidate)
        key = (start, end)
        if key in seen:
            continue
        matches.append({"start": start, "end": end, "text": candidate})
        seen.add(key)
        # One exact location per issue is clearer than painting every repeated
        # word red. Duplicate-scene issues already carry separate evidence.
        break
    if not matches:
        # Some deterministic gates describe the conflict instead of quoting it
        # verbatim (for example "正文把已挂牌公司写成待挂牌").  Locate the
        # longest shared, distinctive phrase in a prose sentence.  Four
        # characters is deliberate: it can mark names such as "深圳物业", but
        # avoids generic two-character words such as "正文" or "问题".
        best: tuple[int, int, str] | None = None
        for sentence_match in re.finditer(r"[^。！？!?\n]{1,260}[。！？!?]?", content):
            sentence = sentence_match.group(0)
            block = SequenceMatcher(None, evidence, sentence).find_longest_match()
            fragment = sentence[block.b:block.b + block.size].strip("“”\"' ：:，,。；;\n\t")
            if len(fragment) < 4:
                continue
            start = content.find(fragment, sentence_match.start(), sentence_match.end())
            if start < 0:
                continue
            candidate_match = (start, start + len(fragment), fragment)
            if best is None or len(fragment) > len(best[2]):
                best = candidate_match
        if best:
            matches.append({"start": best[0], "end": best[1], "text": best[2]})
    return matches


def _chapter_review_required_detail(
    message: str,
    content: str,
    issues: list | None,
) -> dict:
    annotated_issues: list[dict] = []
    for raw in issues or []:
        issue = dict(raw) if isinstance(raw, dict) else {
            "type": "continuity",
            "evidence": str(raw),
            "repair_instruction": "请根据审核意见修改正文",
        }
        issue["matches"] = _review_issue_matches(content, issue)
        annotated_issues.append(issue)
    return {
        "code": "CHAPTER_REVIEW_REQUIRED",
        "message": message,
        "candidate_content": content,
        "word_count": len(content),
        "issues": annotated_issues,
        "actions": ["manual_edit", "regenerate"],
    }


def _normalize_outline_chapters(candidate, revised=None) -> list[dict]:
    """Merge an AI audit revision onto the original batch without losing required fields."""
    candidate = _as_chapter_list(candidate)
    revised = _as_chapter_list(revised)
    revised_by_number = {
        _chapter_number(item.get("chapter_number")): item
        for item in revised
        if isinstance(item, dict) and _chapter_number(item.get("chapter_number")) is not None
    }
    normalized: list[dict] = []
    for index, original in enumerate(candidate):
        if not isinstance(original, dict):
            continue
        chapter_number = _chapter_number(original.get("chapter_number"))
        patch = revised_by_number.get(chapter_number)
        if patch is None and index < len(revised) and isinstance(revised[index], dict):
            indexed = revised[index]
            if _chapter_number(indexed.get("chapter_number")) in (None, chapter_number):
                patch = indexed
        merged = dict(original)
        if patch:
            merged.update({key: value for key, value in patch.items() if value is not None})
        try:
            normalized_item = ChapterOutlineItem.model_validate(merged)
        except Exception:
            # Required text may be absent in a partial audit patch. The original
            # batch remains authoritative for identity and chapter ordering.
            merged["chapter_number"] = chapter_number
            merged["title"] = merged.get("title") or original.get("title") or f"第{chapter_number}章"
            merged["synopsis"] = (
                merged.get("synopsis")
                or original.get("synopsis")
                or "承接前章并推进本阶段主线。"
            )
            normalized_item = ChapterOutlineItem.model_validate(merged)
        normalized.append(normalized_item.model_dump())
    return normalized


def _align_outline_batch_numbers(
    chapters: list[dict],
    start_chapter: int,
    end_chapter: int,
) -> list[dict]:
    """Assign application-owned chapter numbers to an AI-generated batch.

    Web models often restart later batches at 1. Trusting those numbers makes
    every batch overwrite chapters 1-5 while progress falsely advances.
    """
    expected_numbers = list(range(start_chapter, end_chapter + 1))
    if len(chapters) != len(expected_numbers):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                f"大纲批次数量不完整：请求第 {start_chapter}-{end_chapter} 章，"
                f"应返回 {len(expected_numbers)} 章，实际返回 {len(chapters)} 章。"
                "本批未写入，请重试。"
            ),
        )

    supplied_numbers = [_chapter_number(item.get("chapter_number")) for item in chapters]
    if supplied_numbers == expected_numbers:
        return chapters

    aligned: list[dict] = []
    for chapter_number, item in zip(expected_numbers, chapters):
        corrected = dict(item)
        corrected["chapter_number"] = chapter_number
        aligned.append(corrected)
    return aligned


def _apply_dialogue_and_relationship_changes(
    ledger: dict,
    chapter_outline: dict,
    chapter_number: int,
) -> dict:
    """Apply explicit outline-approved relationship/address changes in economy mode."""
    profiles = ledger.setdefault("dialogue_profiles", {})
    relationship_states = ledger.setdefault("relationship_states", [])

    for change in chapter_outline.get("relationship_changes") or []:
        if not isinstance(change, dict):
            continue
        record = dict(change)
        record.setdefault("effective_chapter", chapter_number)
        relationship_states.append(record)

    for change in chapter_outline.get("address_changes") or []:
        if not isinstance(change, dict):
            continue
        speaker = (
            change.get("speaker")
            or change.get("from_character")
            or change.get("character")
        )
        target = change.get("target") or change.get("to_character")
        new_address = (
            change.get("new_address")
            or change.get("new")
            or change.get("address")
        )
        if not speaker or not target or not new_address:
            continue
        profile = profiles.setdefault(
            str(speaker),
            {
                "languages": [],
                "forbidden_languages": [],
                "default_register": "",
                "speech_habits": [],
                "addresses": {},
                "address_history": [],
            },
        )
        addresses = profile.setdefault("addresses", {})
        old_address = addresses.get(str(target), change.get("old_address") or change.get("old"))
        addresses[str(target)] = str(new_address)
        profile.setdefault("address_history", []).append({
            "target": str(target),
            "old": old_address,
            "new": str(new_address),
            "effective_chapter": change.get("effective_chapter") or chapter_number,
            "reason": change.get("reason") or change.get("description") or "",
        })
    return ledger


def _preserve_stable_dialogue_state(
    previous_ledger: dict,
    updated_ledger: dict,
    chapter_outline: dict,
    chapter_number: int,
) -> dict:
    """Preserve aliases, languages and directed addresses across canon updates.

    AI extraction may update plot and asset state, but it cannot replace a
    long-term dialogue rule from one incidental line. Such rules change only
    through explicit, approved outline changes.
    """
    previous_ledger = previous_ledger if isinstance(previous_ledger, dict) else {}
    updated_ledger = updated_ledger if isinstance(updated_ledger, dict) else {}
    updated_ledger["dialogue_profiles"] = deepcopy(
        previous_ledger.get("dialogue_profiles", {})
    )
    updated_ledger["relationship_states"] = deepcopy(
        previous_ledger.get("relationship_states", [])
    )
    return _apply_dialogue_and_relationship_changes(
        updated_ledger,
        chapter_outline,
        chapter_number,
    )


class NovelGenerateService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.novel_repo = NovelRepository(db)
        self.chapter_repo = ChapterRepository(db)
        self.content_repo = ChapterContentRepository(db)
        self.ai_config_repo = AIConfigRepository(db)

    async def generate_outline(self, req: GenerateNovelOutlineRequest, owner_id: int) -> OutlineResult:
        logger.info(f"generate_outline start: novel_id={req.novel_id}, total_chapters={req.total_chapters}, "
                    f"start={req.start_chapter}, end={req.end_chapter}, owner_id={owner_id}")
        novel = await self.novel_repo.get_by_id_and_owner(req.novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        ai_config = await resolve_generation_config(
            self.ai_config_repo,
            req,
            explicit_config_id=req.ai_config_id,
            entity_config_id=novel.ai_config_id,
        )

        logger.info(f"Using AI config: {ai_config.name if ai_config else 'None'}")

        end_chapter = req.end_chapter or req.total_chapters
        is_partial = end_chapter < req.total_chapters

        roadmap = _json_value(novel.story_roadmap, {})
        if roadmap.get("total_chapters") != req.total_chapters or not roadmap.get("stages"):
            roadmap = await ai_service.generate_story_roadmap(
                title=novel.title,
                genre=novel.genre,
                synopsis=novel.synopsis,
                total_chapters=req.total_chapters,
                ai_config=ai_config,
            )
        state_ledger = _json_value(novel.state_ledger, {})
        if not state_ledger:
            protagonist = roadmap.get("protagonist", {})
            initial = protagonist.get("initial_state", {})
            state_ledger = {
                "current_chapter": 0,
                "time_place": "",
                "protagonist": {
                    "name": protagonist.get("name", ""),
                    "identity": protagonist.get("identity", ""),
                    "career": initial.get("career", ""),
                    "wealth": initial.get("wealth", ""),
                    "cash": initial.get("cash", ""),
                    "assets": initial.get("assets", []),
                    "debts": initial.get("debts", []),
                    "abilities": initial.get("abilities", []),
                    "reputation": "",
                    "injuries": [],
                    "relationships": initial.get("relationships", []),
                    "knowledge": [],
                    "items": [],
                    "promises": [],
                    "open_conflicts": [],
                },
                "supporting_characters": [],
                "dialogue_profiles": roadmap.get("dialogue_profiles", {}),
                "relationship_states": roadmap.get("relationship_states", []),
            }
        canon_facts = normalize_canon_facts(_json_value(novel.canon_facts, []))
        state_ledger = normalize_state_ledger(
            state_ledger, canon_facts,
            current_chapter=int(state_ledger.get("current_chapter") or 0),
        )
        audit_log = _json_value(novel.continuity_audits, [])

        # Every later batch must receive the already accepted outline as canon.
        # Passing only a short theme caused chapter 6/11/16 batch boundaries to
        # invent a new protagonist and restart an unrelated plot.
        existing_chapters: list = []
        existing_theme = ""
        if novel.outline:
            try:
                existing = json.loads(novel.outline)
                existing_chapters = existing.get("chapters", [])
                existing_theme = existing.get("theme", "")
            except Exception:
                logger.warning("Ignoring malformed stored outline for novel %s", novel.id)
        previous_chapters = [
            chapter
            for chapter in existing_chapters
            if chapter.get("chapter_number", 0) < req.start_chapter
        ]

        database_contract = (
            "\n\n【数据库版 Skill 固定路线图】\n"
            + json.dumps(roadmap, ensure_ascii=False)
            + "\n【当前正史人物与资产状态】\n"
            + json.dumps(state_ledger, ensure_ascii=False)
            + "\n【不可逆正史事实】\n"
            + json.dumps(canon_facts[-100:], ensure_ascii=False)
        )
        try:
            outline_json = await ai_service.generate_novel_outline(
                title=novel.title,
                genre=novel.genre,
                synopsis=novel.synopsis,
                total_chapters=req.total_chapters,
                start_chapter=req.start_chapter,
                end_chapter=end_chapter,
                theme=req.theme or existing_theme,
                system_prompt=(req.system_prompt or novel.system_prompt or "") + database_contract,
                ai_config=ai_config,
                previous_chapters=previous_chapters,
            )
            logger.info(f"generate_novel_outline success, json length={len(outline_json)}")
        except Exception as e:
            logger.error(f"generate_novel_outline failed: {e}", exc_info=True)
            raise

        outline_data = json.loads(outline_json)
        candidate_chapters = _align_outline_batch_numbers(
            _normalize_outline_chapters(outline_data.get("chapters", [])),
            req.start_chapter,
            end_chapter,
        )
        last_issues: list = []
        approved = req.economy_mode
        attempts = 0
        for attempts in (() if req.economy_mode else range(1, 4)):
            try:
                audit = await ai_service.audit_outline_candidate(
                    synopsis=novel.synopsis,
                    roadmap=roadmap,
                    state_ledger=state_ledger,
                    canon_facts=canon_facts,
                    previous_chapters=previous_chapters,
                    candidate_chapters=candidate_chapters,
                    ai_config=ai_config,
                )
            except HTTPException as exc:
                logger.warning(
                    "outline audit response failed on attempt %s for chapters %s-%s: %s",
                    attempts,
                    req.start_chapter,
                    end_chapter,
                    exc.detail,
                )
                last_issues = [{
                    "type": "audit_response_format",
                    "evidence": str(exc.detail),
                    "repair_instruction": "Retry the continuity audit with strict JSON output.",
                }]
                continue
            last_issues = _as_issue_list(audit.get("issues"))
            revised = _as_chapter_list(audit.get("revised_chapters"))
            if _as_approved(audit.get("approved")):
                candidate_chapters = _align_outline_batch_numbers(
                    _normalize_outline_chapters(candidate_chapters, revised),
                    req.start_chapter,
                    end_chapter,
                )
                approved = True
                break
            if revised:
                candidate_chapters = _align_outline_batch_numbers(
                    _normalize_outline_chapters(candidate_chapters, revised),
                    req.start_chapter,
                    end_chapter,
                )
            if attempts < 3:
                repaired = await ai_service.revise_outline_candidate(
                    synopsis=novel.synopsis,
                    roadmap=roadmap,
                    state_ledger=state_ledger,
                    canon_facts=canon_facts,
                    previous_chapters=previous_chapters,
                    candidate_chapters=candidate_chapters,
                    issues=last_issues,
                    ai_config=ai_config,
                )
                if repaired:
                    candidate_chapters = _align_outline_batch_numbers(
                        _normalize_outline_chapters(candidate_chapters, repaired),
                        req.start_chapter,
                        end_chapter,
                    )
        audit_log.append(
            _audit_entry(
                "outline",
                f"{req.start_chapter}-{end_chapter}",
                approved,
                attempts,
                last_issues,
            )
        )
        if not approved:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "大纲连续性审核未通过，已自动返修 3 次，未写入数据库",
                    "issues": last_issues,
                },
            )
        outline_data["chapters"] = candidate_chapters

        # Merge into existing outline stored on novel (append new chapters)
        new_chapters = candidate_chapters
        try:
            response_chapters = [ChapterOutlineItem(**chapter) for chapter in new_chapters]
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"审核后的大纲缺少必要字段，未写入数据库：{exc}",
            )
        new_chapter_numbers = {ch["chapter_number"] for ch in new_chapters}
        merged_chapters = [ch for ch in existing_chapters if ch["chapter_number"] not in new_chapter_numbers]
        merged_chapters.extend(new_chapters)
        merged_chapters.sort(key=lambda c: c["chapter_number"])

        merged_theme = outline_data.get("theme") or existing_theme
        merged_outline = {
            "total_chapters": req.total_chapters,
            "theme": merged_theme,
            "chapters": merged_chapters,
        }
        novel = await self.novel_repo.update(
            novel,
            outline=json.dumps(merged_outline, ensure_ascii=False),
            total_chapters=req.total_chapters,
            story_roadmap=json.dumps(roadmap, ensure_ascii=False),
            state_ledger=json.dumps(state_ledger, ensure_ascii=False),
            canon_facts=json.dumps(canon_facts, ensure_ascii=False),
            continuity_audits=json.dumps(audit_log[-200:], ensure_ascii=False),
        )
        await self.db.commit()

        return OutlineResult(
            total_chapters=req.total_chapters,
            theme=merged_theme,
            chapters=response_chapters,
            is_partial=is_partial,
        )

    async def generate_chapter_content(
        self, chapter_id: int, req: GenerateChapterRequest, owner_id: int
    ) -> GenerateChapterResult:
        if req.free_mode:
            req.economy_mode = True
        # Get chapter and verify ownership
        chapter = await self.chapter_repo.get(chapter_id)
        if not chapter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

        novel = await self.novel_repo.get_by_id_and_owner(chapter.novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        existing_content = await self.content_repo.get_latest(chapter_id)
        existing_text = getattr(existing_content, "content", "")
        if isinstance(existing_text, str) and existing_text.strip() and not req.regenerate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "本章已有正式正文，已阻止重复生成和重复计费。"
                    "如需修改请直接编辑并保存；重新生成必须先通过专用的本章回滚流程，"
                    "同步撤销该章账本与不可逆事实。"
                ),
            )
        if req.regenerate:
            if not isinstance(existing_text, str) or not existing_text.strip():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="本章尚无正式正文，请使用普通生成。",
                )
            for later_chapter in await self.chapter_repo.get_by_novel(chapter.novel_id):
                if later_chapter.chapter_number <= chapter.chapter_number:
                    continue
                later_content = await self.content_repo.get_latest(later_chapter.id)
                # A later outline chapter may exist without a ChapterContent row yet.
                # Read the value once and never dereference the optional ORM object
                # after falling back to an empty string.
                later_text = getattr(later_content, "content", "")
                if isinstance(later_text, str) and later_text.strip():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            f"第{later_chapter.chapter_number}章已有正文，不能单独重生成第"
                            f"{chapter.chapter_number}章。请先处理后续章节，避免连续性账本失效。"
                        ),
                    )
            _delete_standard_checkpoint(chapter_id)
        elif req.restart_failed_generation:
            # A rejected candidate is not a formal ChapterContent row.  The
            # explicit "重新生成" action must discard its safe-segment cache so
            # a fresh AI draft is requested instead of replaying the same text.
            _delete_standard_checkpoint(chapter_id)

        ai_config = await resolve_generation_config(
            self.ai_config_repo,
            req,
            explicit_config_id=req.ai_config_id,
            entity_config_id=novel.ai_config_id,
        )

        roadmap = _json_value(novel.story_roadmap, {})
        if not roadmap.get("stages"):
            roadmap = await ai_service.generate_story_roadmap(
                title=novel.title,
                genre=novel.genre,
                synopsis=novel.synopsis,
                total_chapters=novel.total_chapters or max(chapter.chapter_number, 1),
                ai_config=ai_config,
            )
        state_ledger = _json_value(novel.state_ledger, {})
        if not state_ledger:
            legacy_graph = _json_value(novel.knowledge_graph, {})
            state_ledger = legacy_graph.get("continuity") or {
                "current_chapter": max(chapter.chapter_number - 1, 0),
                "time_place": "",
                "protagonist": {
                    "name": roadmap.get("protagonist", {}).get("name", ""),
                    "identity": roadmap.get("protagonist", {}).get("identity", ""),
                    "career": "",
                    "wealth": "",
                    "cash": "",
                    "assets": [],
                    "debts": [],
                    "abilities": [],
                    "reputation": "",
                    "injuries": [],
                    "relationships": [],
                    "knowledge": [],
                    "items": [],
                    "promises": [],
                    "open_conflicts": [],
                },
                "supporting_characters": [],
                "dialogue_profiles": roadmap.get("dialogue_profiles", {}),
                "relationship_states": roadmap.get("relationship_states", []),
            }
        canon_facts = normalize_canon_facts(_json_value(novel.canon_facts, []))
        if req.regenerate:
            state_ledger = _rollback_ledger_for_regeneration(
                state_ledger, chapter.chapter_number,
            )
            canon_facts = _rollback_facts_for_regeneration(
                canon_facts, chapter.chapter_number,
            )
        state_ledger = normalize_state_ledger(
            state_ledger, canon_facts,
            current_chapter=int(state_ledger.get("current_chapter") or 0),
        )
        audit_log = _json_value(novel.continuity_audits, [])
        if req.regenerate:
            audit_log = [
                item for item in audit_log
                if not (
                    isinstance(item, dict)
                    and item.get("kind") in {"draft", "manual_revision"}
                    and str(item.get("chapter_range")) == str(chapter.chapter_number)
                )
            ]

        chapter_outline = {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "synopsis": chapter.synopsis or "",
            "speech_constraints": [],
            "relationship_changes": [],
            "address_changes": [],
        }
        outline_data = _json_value(novel.outline, {}) if novel.outline else {}
        if outline_data:
            chapter_outline = next(
                (
                    item
                    for item in outline_data.get("chapters", [])
                    if item.get("chapter_number") == chapter.chapter_number
                ),
                chapter_outline,
            )
        future_boundaries = []
        for item in outline_data.get("chapters", []):
            number = int(item.get("chapter_number") or 0)
            if not (chapter.chapter_number < number <= chapter.chapter_number + 5):
                continue
            synopsis = str(item.get("synopsis") or "")
            protected_events = []
            for match in re.finditer(
                r"(?:正式|最终|已经|完成)?(?:取得|注册|成立|收购|签订|投入|租用|购买|交付)"
                r"[^，。；]{2,32}",
                synopsis,
            ):
                protected_events.append(match.group(0))
            future_boundaries.append({
                "chapter_number": number,
                "title": item.get("title", ""),
                "synopsis": synopsis,
                "protected_events": protected_events,
                "rule": "当前章只可铺垫，不得提前完成该章结果事件",
            })
        chapter_outline = dict(chapter_outline)
        chapter_outline["future_boundaries"] = future_boundaries

        canonical_context = relevant_canon_context(
            state_ledger, canon_facts, chapter_outline, max_facts=160,
        )

        # Build context
        context_parts = []
        context_parts.append(f"小说：{novel.title}\n故事大概：{novel.synopsis}")
        context_parts.append(
            "【固定全书阶段路线图】\n"
            + json.dumps(roadmap, ensure_ascii=False)
            + "\n【当前正史人物、身份与资产账本】\n"
            + json.dumps(canonical_context["current_state"], ensure_ascii=False)
            + "\n【与本章相关的有效不可逆正史事实】\n"
            + json.dumps(canonical_context["relevant_irreversible_facts"], ensure_ascii=False)
            + "\n【本章大纲、语言、称呼与关系变化约束】\n"
            + json.dumps(chapter_outline, ensure_ascii=False)
            + "\n【未来五章事件边界】\n"
            + json.dumps(future_boundaries, ensure_ascii=False)
            + "\n未来章节事件只能铺垫，不得在本章提前签约、付款、取得资产或完成结果。"
        )

        # Inject knowledge graph (characters & events so far)
        if novel.knowledge_graph:
            try:
                kg = json.loads(novel.knowledge_graph)
                chars = kg.get("characters", [])
                events = kg.get("events", [])
                if chars or events:
                    kg_lines = ["【已出现的人物关系】"]
                    for c in chars:
                        rels = "、".join(f"{r['target']}({r['relation']})" for r in c.get("relations", []))
                        kg_lines.append(f"- {c['name']}（{c.get('role','')}）：{c.get('description','')}{'；关联：'+rels if rels else ''}")
                    kg_lines.append("【已发生的关键事件】")
                    for e in events[-20:]:  # last 20 events to avoid context overflow
                        kg_lines.append(f"- 第{e.get('chapter','')}章 {e.get('title','')}：{e.get('description','')}")
                    open_threads = kg.get("open_threads", [])
                    if open_threads:
                        kg_lines.append("【仍待兑现的线索与承诺】")
                        for item in open_threads[-20:]:
                            kg_lines.append(f"- {item.get('thread', '')}（最后涉及第{item.get('last_chapter', '')}章）")
                    continuity = kg.get("continuity")
                    if continuity:
                        kg_lines.append("【下一章不可违背的连续性状态】")
                        kg_lines.append(json.dumps(continuity, ensure_ascii=False))
                    context_parts.append("\n".join(kg_lines))
            except Exception:
                pass

        # KEY LOGIC: Get previous chapter ending for continuity
        previous_ending = ""
        if chapter.chapter_number > 1:
            prev_chapter = await self.chapter_repo.get_by_number(novel.id, chapter.chapter_number - 1)
            if prev_chapter:
                prev_content = await self.content_repo.get_latest(prev_chapter.id)
                if prev_content and prev_content.content:
                    # Keep enough of the previous ending to preserve actions,
                    # item custody and time transitions rather than only tone.
                    snippet = prev_content.content[-2000:]
                    previous_ending = snippet
                    context_parts.append(
                        f"上一章（第 {prev_chapter.chapter_number} 章：{prev_chapter.title}）结尾内容：\n{snippet}\n"
                        f"请确保本章内容与上一章自然衔接，情节连贯。"
                    )

        if req.extra_context:
            context_parts.append(req.extra_context)

        # Build prompt
        prompt = f"第 {chapter.chapter_number} 章：{chapter.title}\n"
        if chapter.synopsis:
            prompt += f"本章简介：{chapter.synopsis}\n"
        prompt += (
            "请生成4500—5500字的完整小说正文。只输出角色世界内的正文，不输出章节加工说明。"
            "所有交易必须写明期初持仓、买入、卖出、费用与期末余额；所有时间、权限、称呼和历史制度必须可核对。"
        )

        preflight_issues = _outline_preflight_issues(chapter_outline, state_ledger)
        if preflight_issues:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "本章大纲未通过生成前硬规则，尚未调用AI、未产生正文费用",
                    "issues": preflight_issues,
                },
            )

        full_context = "\n\n".join(context_parts)
        approved = False
        last_issues: list = []
        review_warnings: list = []
        attempts = 0
        fingerprint: str | None = None
        segments: list[str] = []

        if req.economy_mode:
            content = await ai_service.generate_chapter(
                prompt=prompt,
                context=full_context,
                system_prompt=req.system_prompt or novel.system_prompt,
                ai_config=ai_config,
            )
            local_issues = _local_chapter_issues(content, chapter_outline, state_ledger)
            attempts = 1
            audit = await ai_service.audit_chapter_candidate(
                chapter_number=chapter.chapter_number,
                chapter_outline=chapter_outline,
                content=content,
                roadmap=roadmap,
                state_ledger=state_ledger,
                canon_facts=canon_facts,
                previous_ending=previous_ending,
                ai_config=ai_config,
            )
            audit_issues = [] if _as_approved(audit.get("approved")) else _validated_ai_audit_issues(
                audit.get("issues"), content
            )
            last_issues = local_issues + audit_issues
            if last_issues:
                content = await ai_service.revise_chapter_candidate(
                    original_content=content,
                    issues=last_issues,
                    context=full_context,
                    prompt=prompt,
                    ai_config=ai_config,
                )
                attempts = 2
                final_local = _local_chapter_issues(content, chapter_outline, state_ledger)
                final_audit = await ai_service.audit_chapter_candidate(
                    chapter_number=chapter.chapter_number,
                    chapter_outline=chapter_outline,
                    content=content,
                    roadmap=roadmap,
                    state_ledger=state_ledger,
                    canon_facts=canon_facts,
                    previous_ending=previous_ending,
                    ai_config=ai_config,
                )
                final_audit_issues = [] if _as_approved(final_audit.get("approved")) else (
                    _validated_ai_audit_issues(final_audit.get("issues"), content)
                )
                # Semantic findings have already driven one complete revision.
                # They are retained for review but may not create an infinite
                # regenerate/reject loop. Only deterministic issues still block.
                review_warnings = final_audit_issues
                last_issues = final_local
                approved = not final_local
            else:
                approved = True
        else:
            total_segments = 3
            active_stage = next(
                (
                    item
                    for item in roadmap.get("stages", [])
                    if int(item.get("start_chapter", 0) or 0)
                    <= chapter.chapter_number
                    <= int(item.get("end_chapter", 0) or 0)
                ),
                {},
            )
            standard_context = json.dumps(
                {
                    "novel": {
                        "title": novel.title,
                        "genre": novel.genre,
                        "synopsis": novel.synopsis,
                    },
                    "active_stage": active_stage,
                    "state_ledger": canonical_context["current_state"],
                    "relevant_canon_facts": canonical_context["relevant_irreversible_facts"],
                    "chapter_outline": chapter_outline,
                    "previous_ending": previous_ending,
                    "extra_context": req.extra_context or "",
                },
                ensure_ascii=False,
            )
            model_name = str(getattr(ai_config, "model", "") or "default")
            fingerprint = _checkpoint_fingerprint(
                chapter_id, prompt, standard_context, model_name
            )
            checkpoint_payload = _load_standard_checkpoint_payload(chapter_id, fingerprint)
            segments = checkpoint_payload["segments"]
            resumed_approved_content = checkpoint_payload.get("approved_content")
            if not isinstance(resumed_approved_content, str) or not (
                3500 <= len(resumed_approved_content.strip()) <= 6500
            ):
                resumed_approved_content = ""
            if len(segments) > total_segments:
                segments = segments[:total_segments]
            for segment_index in range(len(segments) + 1, total_segments + 1):
                completed = "\n\n".join(segments)
                segment = ""
                segment_feedback: list[dict] = []
                for segment_attempt in range(1, 4):
                    segment = await ai_service.generate_chapter_segment(
                        prompt=prompt,
                        context=standard_context,
                        segment_index=segment_index,
                        total_segments=total_segments,
                        completed_content=completed,
                        ai_config=ai_config,
                        system_prompt=req.system_prompt or novel.system_prompt,
                        retry_feedback=segment_feedback,
                    )
                    segment = _normalize_standard_segment(segment)
                    overlap_issues = (
                        _candidate_segment_issues(
                            segments, len(segments), segment
                        )
                        if _is_valid_standard_segment(segment) else []
                    )
                    if _is_valid_standard_segment(segment) and not overlap_issues:
                        break
                    segment_feedback = overlap_issues or [{
                        "type": "invalid_segment_shape",
                        "evidence": f"候选段长度{len((segment or '').strip())}，或结尾/引号未闭合",
                        "conflict_with": "分段必须完整且可直接拼接",
                        "repair_instruction": "输出800—2100字的完整连续正文，并以闭合句子结束",
                    }]
                    logger.warning(
                        "Discarded invalid or duplicate chapter segment chapter=%s segment=%s attempt=%s length=%s issues=%s",
                        chapter_id,
                        segment_index,
                        segment_attempt,
                        len((segment or "").strip()),
                        [item.get("type") for item in segment_feedback],
                    )
                if not _is_valid_standard_segment(segment) or segment_feedback and (
                    _candidate_segment_issues(segments, len(segments), segment)
                ):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            f"标准模式第{segment_index}/{total_segments}段连续3次返回空白、"
                            "过短、截断或重复前文的内容；无效内容未写入检查点。"
                            "重新点击后将从本段继续。"
                        ),
                    )
                segments.append(segment.strip())
                _save_standard_checkpoint(chapter_id, fingerprint, segments)

            initial_local = [] if resumed_approved_content else (
                _local_chapter_issues(
                    "\n\n".join(segments), chapter_outline, state_ledger
                ) + _cross_segment_issues(segments)
            )
            if initial_local:
                for index in sorted(_segments_for_issues(segments, initial_local)):
                    revised_segment = (
                        await ai_service.revise_chapter_segment(
                            segment=segments[index],
                            segment_index=index + 1,
                            total_segments=total_segments,
                            issues=initial_local,
                            context=standard_context,
                            prompt=prompt,
                            previous_tail=segments[index - 1] if index else "",
                            next_head=segments[index + 1] if index + 1 < len(segments) else "",
                            ai_config=ai_config,
                        )
                    ).strip()
                    revised_segment = _normalize_standard_segment(revised_segment)
                    overlap_issues = (
                        _candidate_segment_issues(segments, index, revised_segment)
                        if _is_valid_standard_segment(revised_segment) else []
                    )
                    if _is_valid_standard_segment(revised_segment) and not overlap_issues:
                        segments[index] = revised_segment
                        _save_standard_checkpoint(chapter_id, fingerprint, segments)
                    else:
                        logger.warning(
                            "Discarded invalid or duplicate revised segment chapter=%s segment=%s length=%s",
                            chapter_id,
                            index + 1,
                            len(revised_segment),
                        )

            content = resumed_approved_content or "\n\n".join(segments)
            attempts = 1
            audit = {"approved": True, "issues": []} if resumed_approved_content else (
                await ai_service.audit_chapter_candidate(
                    chapter_number=chapter.chapter_number,
                    chapter_outline=chapter_outline,
                    content=content,
                    roadmap=roadmap,
                    state_ledger=state_ledger,
                    canon_facts=canon_facts,
                    previous_ending=previous_ending,
                    ai_config=ai_config,
                )
            )
            current_local = (
                _local_chapter_issues(content, chapter_outline, state_ledger)
                + _cross_segment_issues(segments)
            )
            audit_issues = [] if _as_approved(audit.get("approved")) else _validated_ai_audit_issues(
                audit.get("issues"), content
            )
            last_issues = current_local + audit_issues
            if last_issues:
                for index in sorted(_segments_for_issues(segments, last_issues)):
                    revised_segment = (
                        await ai_service.revise_chapter_segment(
                            segment=segments[index],
                            segment_index=index + 1,
                            total_segments=total_segments,
                            issues=last_issues,
                            context=standard_context,
                            prompt=prompt,
                            previous_tail=segments[index - 1] if index else "",
                            next_head=segments[index + 1] if index + 1 < len(segments) else "",
                            ai_config=ai_config,
                        )
                    ).strip()
                    revised_segment = _normalize_standard_segment(revised_segment)
                    overlap_issues = (
                        _candidate_segment_issues(segments, index, revised_segment)
                        if _is_valid_standard_segment(revised_segment) else []
                    )
                    if _is_valid_standard_segment(revised_segment) and not overlap_issues:
                        segments[index] = revised_segment
                        _save_standard_checkpoint(chapter_id, fingerprint, segments)
                    else:
                        logger.warning(
                            "Discarded invalid or duplicate revised segment chapter=%s segment=%s length=%s",
                            chapter_id,
                            index + 1,
                            len(revised_segment),
                        )
                content = "\n\n".join(segments)
                attempts = 2
                final_local = (
                    _local_chapter_issues(content, chapter_outline, state_ledger)
                    + _cross_segment_issues(segments)
                )
                final_audit = await ai_service.audit_chapter_candidate(
                    chapter_number=chapter.chapter_number,
                    chapter_outline=chapter_outline,
                    content=content,
                    roadmap=roadmap,
                    state_ledger=state_ledger,
                    canon_facts=canon_facts,
                    previous_ending=previous_ending,
                    ai_config=ai_config,
                )
                final_audit_issues = [] if _as_approved(final_audit.get("approved")) else (
                    _validated_ai_audit_issues(final_audit.get("issues"), content)
                )
                review_warnings = final_audit_issues
                last_issues = final_local
                approved = not final_local
            else:
                approved = True

            # A whole-chapter rewrite is reserved for deterministic failures.
            # Rewriting solely because a semantic reviewer raised another
            # subjective concern caused "越修越错" and duplicate scenes.
            if not approved and last_issues:
                pre_stitch_content = content
                pre_stitch_local = list(last_issues)
                stitched = (
                    await ai_service.revise_chapter_candidate(
                        original_content=content,
                        issues=last_issues,
                        context=standard_context,
                        prompt=prompt,
                        ai_config=ai_config,
                    )
                ).strip()
                stitched_local = _local_chapter_issues(
                    stitched, chapter_outline, state_ledger
                )
                attempts = 3
                if not stitched_local:
                    content = stitched
                    last_issues = []
                    approved = True
                else:
                    # Never replace a better paid draft with a repair that adds
                    # duplicated scenes, truncation, bad arithmetic or meta text.
                    content = pre_stitch_content
                    last_issues = pre_stitch_local
                    approved = False

        audit_log.append(
            _audit_entry(
                "draft",
                str(chapter.chapter_number),
                approved,
                attempts,
                last_issues,
                review_warnings,
            )
        )
        if approved and review_warnings:
            logger.info(
                "Chapter %s accepted after bounded repair with %s advisory warning(s): %s",
                chapter.chapter_number,
                len(review_warnings),
                [str(item.get("type") or "continuity") for item in review_warnings],
            )
        if not approved:
            logger.warning(
                "Chapter %s rejected by deterministic gates after %s attempt(s): %s",
                chapter.chapter_number,
                attempts,
                json.dumps(last_issues, ensure_ascii=False),
            )
            if fingerprint:
                bad_indexes = _segments_for_issues(segments, last_issues)
                retry_from = min(bad_indexes) if bad_indexes else max(len(segments) - 1, 0)
                safe_segments = segments[:retry_from]
                _save_standard_checkpoint(
                    chapter_id,
                    fingerprint,
                    safe_segments,
                    stage="repair_retry_pending",
                    candidate_content=content,
                    approved_content=None,
                    canon_update=None,
                    last_issues=last_issues,
                    recovery_note=(
                        f"返修仍未通过，已自动回退到第{retry_from}段之后重新生成"
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_chapter_review_required_detail(
                    "正文仍存在可验证的确定性错误。请选择本地手动修改，或重新调用 AI 生成。",
                    content,
                    last_issues,
                ),
            )

        if fingerprint:
            _save_standard_checkpoint(
                chapter_id,
                fingerprint,
                segments,
                stage="prose_approved",
                approved_content=content,
                approved_at=datetime.now(timezone.utc).isoformat(),
                last_issues=[],
                review_warnings=review_warnings,
            )

        # Build layer 2/3 from the approved prose, never from the outline alone.
        checkpoint_payload = (
            _load_standard_checkpoint_payload(chapter_id, fingerprint)
            if fingerprint else {}
        )
        canon_update = checkpoint_payload.get("canon_update")
        if not isinstance(canon_update, dict):
            canon_update = await ai_service.extract_canon_update(
                chapter_number=chapter.chapter_number,
                chapter_title=chapter.title,
                content=content,
                existing_ledger=state_ledger,
                existing_facts=canon_facts,
                ai_config=ai_config,
            )
            if fingerprint:
                _save_standard_checkpoint(
                    chapter_id,
                    fingerprint,
                    segments,
                    stage="canon_extracted",
                    approved_content=content,
                    canon_update=canon_update,
                )
        updated_ledger = canon_update.get("state_ledger")
        extracted_facts = canon_update.get("new_irreversible_facts")
        if not isinstance(updated_ledger, dict) or not isinstance(
            updated_ledger.get("protagonist"), dict
        ) or not isinstance(extracted_facts, list):
            invalid_issues = [{
                "type": "canon_extraction",
                "evidence": "state_ledger/protagonist/new_irreversible_facts结构不完整",
                "conflict_with": "四层架构的实际正文状态",
                "repair_instruction": "重新执行状态提取，不得回退为大纲推测值",
            }]
            _invalidate_checkpoint_canon_update(
                chapter_id, fingerprint, segments, content, invalid_issues,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_chapter_review_required_detail(
                    "正文已生成，但实际状态提取无效；请选择本地手动修改，或重新调用 AI 生成。",
                    content,
                    invalid_issues,
                ),
            )
        updated_ledger = normalize_state_ledger(
            updated_ledger, canon_facts,
            current_chapter=chapter.chapter_number,
        )
        updated_ledger = _preserve_stable_dialogue_state(
            state_ledger, updated_ledger, chapter_outline, chapter.chapter_number,
        )
        updated_ledger = merge_structured_history(state_ledger, updated_ledger)
        ledger_issues = structured_ledger_issues(updated_ledger)
        if ledger_issues:
            _invalidate_checkpoint_canon_update(
                chapter_id, fingerprint, segments, content, ledger_issues,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_chapter_review_required_detail(
                    "正文已生成，但结构化账本不完整；请选择本地手动修改，或重新调用 AI 生成。",
                    content,
                    ledger_issues,
                ),
            )
        updated_ledger = _apply_dialogue_and_relationship_changes(
            updated_ledger,
            chapter_outline,
            chapter.chapter_number,
        )
        new_facts = []
        for fact in extracted_facts:
            if not isinstance(fact, dict) or not str(fact.get("fact") or "").strip():
                continue
            normalized = dict(fact)
            normalized["chapter"] = chapter.chapter_number
            normalized.setdefault("type", "event")
            normalized.setdefault("cause", "来自已通过审核的最终正文")
            new_facts.append(normalized)
        existing_fact_keys = {
            (item.get("chapter"), item.get("type"), item.get("fact"))
            for item in canon_facts
            if isinstance(item, dict)
        }
        for fact in new_facts:
            key = (fact.get("chapter"), fact.get("type"), fact.get("fact"))
            if key not in existing_fact_keys:
                canon_facts.append(fact)
                existing_fact_keys.add(key)

        canon_facts = apply_fact_status_updates(
            canon_facts, canon_update.get("fact_status_updates", []),
        )
        updated_ledger = normalize_state_ledger(
            updated_ledger, canon_facts,
            current_chapter=chapter.chapter_number,
        )
        coverage_issues = canon_update_coverage_issues(
            state_ledger, updated_ledger, content, chapter.chapter_number,
        )
        if coverage_issues:
            coverage_patch = await ai_service.repair_canon_coverage(
                chapter_number=chapter.chapter_number,
                content=content,
                current_ledger=updated_ledger,
                coverage_issues=coverage_issues,
                ai_config=ai_config,
            )
            patch_fields = (
                "asset_accounts",
                "transaction_ledger",
                "item_custody",
                "timeline",
                "commitments",
                "plot_threads",
                "knowledge_boundaries",
            )
            for field in patch_fields:
                values = coverage_patch.get(field)
                if not isinstance(values, list):
                    continue
                target = updated_ledger.setdefault(field, [])
                if not isinstance(target, list):
                    target = []
                    updated_ledger[field] = target
                known = {
                    json.dumps(item, ensure_ascii=False, sort_keys=True)
                    for item in target
                    if isinstance(item, dict)
                }
                for item in values:
                    if not isinstance(item, dict):
                        continue
                    item = dict(item)
                    item.setdefault("chapter", chapter.chapter_number)
                    marker = json.dumps(item, ensure_ascii=False, sort_keys=True)
                    if marker not in known:
                        target.append(item)
                        known.add(marker)
            updated_ledger = normalize_state_ledger(
                updated_ledger, canon_facts,
                current_chapter=chapter.chapter_number,
            )
            updated_ledger = merge_structured_history(state_ledger, updated_ledger)
            coverage_issues = canon_update_coverage_issues(
                state_ledger, updated_ledger, content, chapter.chapter_number,
            )
        if coverage_issues:
            _invalidate_checkpoint_canon_update(
                chapter_id, fingerprint, segments, content, coverage_issues,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_chapter_review_required_detail(
                    "正文已生成，但关键变化未完整写入结构化账本；请选择本地手动修改，或重新调用 AI 生成。",
                    content,
                    coverage_issues,
                ),
            )

        # Coverage repair may describe the same transaction with `amount`
        # while extraction used `cash_change`. Collapse semantic duplicates
        # once more, then enforce cash conservation before anything is saved.
        updated_ledger = merge_structured_history({}, updated_ledger)
        updated_ledger = _normalize_current_chapter_cash_ownership(
            updated_ledger, chapter.chapter_number,
        )
        updated_ledger, cash_repaired = _repair_cash_snapshot_from_transactions(
            state_ledger, updated_ledger, chapter.chapter_number,
        )
        if cash_repaired:
            cash_text = str(updated_ledger.get("protagonist", {}).get("cash") or "")
            total_text = str(
                updated_ledger.get("protagonist", {}).get("total_assets") or ""
            )
            canon_facts = [
                fact for fact in canon_facts
                if not (
                    isinstance(fact, dict)
                    and int(fact.get("chapter") or 0) == chapter.chapter_number
                    and str(fact.get("type") or "") in {
                        "wealth", "asset", "assets", "finance", "cash"
                    }
                )
            ]
            financial_fact = {
                "chapter": chapter.chapter_number,
                "type": "wealth",
                "fact": (
                    f"本章按主角个人逐笔流水核算，期末现金为{cash_text}"
                    + (f"，总资产为{total_text}" if total_text else "")
                ),
                "cause": "程序依据去重后的主角个人交易流水自动对账",
                "evidence": json.dumps(
                    updated_ledger.get("last_reconciliation", {}),
                    ensure_ascii=False,
                ),
                "importance": "critical",
                "status": "active",
            }
            canon_facts.append(financial_fact)
            canon_facts = normalize_canon_facts(canon_facts)
            updated_ledger = normalize_state_ledger(
                updated_ledger,
                canon_facts,
                current_chapter=chapter.chapter_number,
            )
            normalized_financial_fact = next(
                (
                    fact for fact in reversed(canon_facts)
                    if int(fact.get("chapter") or 0) == chapter.chapter_number
                    and fact.get("type") == "wealth"
                    and "程序依据去重后的主角个人交易流水自动对账"
                    in str(fact.get("cause") or "")
                ),
                financial_fact,
            )
            canon_update["new_irreversible_facts"] = [normalized_financial_fact]
            canon_update["state_ledger"] = updated_ledger
            if fingerprint:
                _save_standard_checkpoint(
                    chapter_id,
                    fingerprint,
                    segments,
                    stage="canon_reconciled",
                    approved_content=content,
                    canon_update=canon_update,
                    last_canon_issues=[],
                )
        snapshots = deepcopy(state_ledger.get("generation_snapshots", {}))
        snapshot = deepcopy(state_ledger)
        snapshot.pop("generation_snapshots", None)
        snapshots[str(chapter.chapter_number)] = snapshot
        updated_ledger["generation_snapshots"] = snapshots
        cash_issues = _ledger_cash_reconciliation_issues(
            state_ledger, updated_ledger, chapter.chapter_number,
        )
        if cash_issues:
            _invalidate_checkpoint_canon_update(
                chapter_id, fingerprint, segments, content, cash_issues,
            )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=_chapter_review_required_detail(
                    "正文已生成，但期末现金与逐笔流水不守恒；请选择本地手动修改，或重新调用 AI 生成。",
                    content,
                    cash_issues,
                ),
            )

        # Web pages can expose visually separated paragraphs as one DOM text
        # node. Never persist a full chapter as an unreadable single line.
        content = normalize_chapter_paragraphs(content)
        word_count = len(content)
        existing = await self.content_repo.get_latest(chapter_id)
        if existing:
            new_version = existing.version + 1
            chapter_content = await self.content_repo.create(
                content=content,
                word_count=word_count,
                status="generated",
                version=new_version,
                chapter_id=chapter_id,
            )
        else:
            chapter_content = await self.content_repo.create(
                content=content,
                word_count=word_count,
                status="generated",
                version=1,
                chapter_id=chapter_id,
            )

        await self.novel_repo.update(
            novel,
            story_roadmap=json.dumps(roadmap, ensure_ascii=False),
            state_ledger=json.dumps(updated_ledger, ensure_ascii=False),
            canon_facts=json.dumps(canon_facts, ensure_ascii=False),
            continuity_audits=json.dumps(audit_log[-200:], ensure_ascii=False),
            # Keep the legacy graph readable by existing graph screens while
            # the four authoritative Skill fields remain separate.
            knowledge_graph=json.dumps(
                {
                    "characters": _json_value(novel.knowledge_graph, {}).get("characters", []),
                    "events": canon_facts[-100:],
                    "open_threads": updated_ledger.get("protagonist", {}).get("open_conflicts", []),
                    "continuity": updated_ledger,
                },
                ensure_ascii=False,
            ),
        )
        await self.db.commit()
        if not req.economy_mode:
            _delete_standard_checkpoint(chapter_id)

        return GenerateChapterResult(
            chapter_id=chapter_id,
            content_id=chapter_content.id,
            content=content,
            word_count=word_count,
        )

    async def batch_generate_chapters(
        self, novel_id: int, req: BatchGenerateChaptersRequest, owner_id: int
    ) -> BatchGenerateResult:
        if req.free_mode:
            req.economy_mode = True
        # Verify novel ownership
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        # Validate configuration before entering the per-chapter error loop so
        # the UI can show one actionable "configure AI" message.
        ai_config = await resolve_generation_config(
            self.ai_config_repo,
            req,
            explicit_config_id=req.ai_config_id,
            entity_config_id=novel.ai_config_id,
        )
        ai_service._resolve(ai_config)

        # Get all chapters, sorted by chapter_number
        chapters = await self.chapter_repo.get_by_novel(novel_id)
        chapters.sort(key=lambda c: c.chapter_number)

        # Filter if only_missing
        if req.only_missing:
            filtered_chapters = []
            for chapter in chapters:
                existing = await self.content_repo.get_latest(chapter.id)
                if not existing or not existing.content:
                    filtered_chapters.append(chapter)
            chapters = filtered_chapters

        # Generate sequentially to ensure continuity
        total = len(chapters)
        succeeded = 0
        failed = 0
        errors = []

        for chapter in chapters:
            try:
                await self.generate_chapter_content(
                    chapter.id,
                    GenerateChapterRequest(
                        generation_mode=req.generation_mode,
                        ai_config_id=req.ai_config_id,
                        system_prompt=req.system_prompt,
                        economy_mode=req.economy_mode,
                        free_mode=req.free_mode,
                        free_provider=req.free_provider,
                    ),
                    owner_id,
                )
                succeeded += 1
            except Exception as e:
                failed += 1
                errors.append({
                    "chapter_id": chapter.id,
                    "chapter_number": chapter.chapter_number,
                    "error": str(e),
                })

        return BatchGenerateResult(
            total=total,
            succeeded=succeeded,
            failed=failed,
            errors=errors,
        )

    async def generate_next_chapter(
        self, novel_id: int, req: GenerateNextChapterRequest, owner_id: int
    ) -> GenerateNextChapterResult:
        if req.free_mode:
            req.economy_mode = True
        # Verify novel ownership
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        # Get last chapter
        last_chapter = await self.chapter_repo.get_last_chapter(novel_id)
        if not last_chapter:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No chapters found")

        # Get last chapter content
        last_content = await self.content_repo.get_latest(last_chapter.id)
        if not last_content or not last_content.content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Last chapter has no content")

        ai_config = await resolve_generation_config(
            self.ai_config_repo,
            req,
            explicit_config_id=req.ai_config_id,
            entity_config_id=novel.ai_config_id,
        )

        roadmap = _json_value(novel.story_roadmap, {})
        if not roadmap.get("stages"):
            roadmap = await ai_service.generate_story_roadmap(
                title=novel.title,
                genre=novel.genre,
                synopsis=novel.synopsis,
                total_chapters=novel.total_chapters or (last_chapter.chapter_number + 1),
                ai_config=ai_config,
            )
        state_ledger = _json_value(novel.state_ledger, {})
        canon_facts = normalize_canon_facts(_json_value(novel.canon_facts, []))
        state_ledger = normalize_state_ledger(
            state_ledger, canon_facts,
            current_chapter=int(state_ledger.get("current_chapter") or 0),
        )
        audit_log = _json_value(novel.continuity_audits, [])

        # Include both the latest scene and the structured continuity memory.
        snippet = last_content.content[-2000:]
        continuity_hint = ""
        if novel.knowledge_graph:
            continuity_hint = f"\n\n当前正史连续性记忆：\n{novel.knowledge_graph[:5000]}"

        # Generate next chapter outline
        sys_msg = novel_skill_prompt("next", req.system_prompt or novel.system_prompt)
        user_msg = (
            f"小说：{novel.title}\n"
            f"故事大概：{novel.synopsis}{continuity_hint}\n\n"
            f"固定阶段路线图：\n{json.dumps(roadmap, ensure_ascii=False)}\n\n"
            f"当前人物与资产账本：\n{json.dumps(state_ledger, ensure_ascii=False)}\n\n"
            f"不可逆事实：\n{json.dumps(canon_facts[-100:], ensure_ascii=False)}\n\n"
            f"上一章（第 {last_chapter.chapter_number} 章：{last_chapter.title}）结尾内容：\n{snippet}\n\n"
            f"请生成第 {last_chapter.chapter_number + 1} 章的标题和简介，以纯 JSON 格式返回：\n"
            '{"title": "章节标题", "synopsis": "本章简介"}'
        )

        from app.services.ai_service import ai_service
        base_url, api_key, model = ai_service._resolve(ai_config)
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await ai_service._call(messages, base_url, api_key, model, json_mode=True)

        next_chapter_data = ai_service._parse_json_response(raw, "next chapter outline")
        candidate = _normalize_outline_chapters([{
            "chapter_number": last_chapter.chapter_number + 1,
            "title": next_chapter_data["title"],
            "synopsis": next_chapter_data.get("synopsis", ""),
        }])
        previous_outline = _json_value(novel.outline, {}).get("chapters", [])
        approved = req.economy_mode
        last_issues: list = []
        attempts = 0
        for attempts in (() if req.economy_mode else range(1, 4)):
            audit = await ai_service.audit_outline_candidate(
                synopsis=novel.synopsis,
                roadmap=roadmap,
                state_ledger=state_ledger,
                canon_facts=canon_facts,
                previous_chapters=previous_outline,
                candidate_chapters=candidate,
                ai_config=ai_config,
            )
            last_issues = _as_issue_list(audit.get("issues"))
            revised = _as_chapter_list(audit.get("revised_chapters"))
            if _as_approved(audit.get("approved")):
                candidate = _normalize_outline_chapters(candidate, revised)
                approved = True
                break
            if revised:
                candidate = _normalize_outline_chapters(candidate, revised)
        if not approved:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "下一章大纲审核未通过，已自动返修 3 次，未写入数据库",
                    "issues": last_issues,
                },
            )
        next_chapter_data = candidate[0]
        audit_log.append(
            _audit_entry(
                "outline",
                str(last_chapter.chapter_number + 1),
                True,
                attempts,
                last_issues,
            )
        )
        await self.novel_repo.update(
            novel,
            story_roadmap=json.dumps(roadmap, ensure_ascii=False),
            continuity_audits=json.dumps(audit_log[-200:], ensure_ascii=False),
        )

        # Create new chapter
        new_chapter = await self.chapter_repo.create(
            title=next_chapter_data["title"],
            chapter_number=last_chapter.chapter_number + 1,
            synopsis=next_chapter_data.get("synopsis", ""),
            novel_id=novel_id,
        )
        await self.db.commit()

        # Generate content
        result = await self.generate_chapter_content(
            new_chapter.id,
            GenerateChapterRequest(
                generation_mode=req.generation_mode,
                ai_config_id=req.ai_config_id,
                system_prompt=req.system_prompt,
                economy_mode=req.economy_mode,
                free_mode=req.free_mode,
                free_provider=req.free_provider,
            ),
            owner_id,
        )

        return GenerateNextChapterResult(
            chapter_id=new_chapter.id,
            chapter_number=new_chapter.chapter_number,
            title=new_chapter.title,
            synopsis=new_chapter.synopsis or "",
            content_id=result.content_id,
        )
