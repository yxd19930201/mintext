import json
import logging
import hashlib
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.repositories.novel_repo import NovelRepository
from app.repositories.chapter_repo import ChapterRepository
from app.repositories.chapter_content_repo import ChapterContentRepository
from app.repositories.ai_config_repo import AIConfigRepository
from app.services.ai_service import ai_service
from app.services.structured_ledger_service import (
    normalize_canon_facts,
    normalize_state_ledger,
)

logger = logging.getLogger(__name__)


MIN_APPEARANCES = 3  # characters appearing fewer times than this are dropped


def _filter_graph(graph: dict) -> dict:
    """Keep only protagonist-related characters.

    Rules:
    - Protagonist = character with the most relations (always kept).
    - Characters: only keep characters appearing ≥ MIN_APPEARANCES times
      across all relations (protagonist always kept).
    """
    characters = graph.get("characters", [])

    if not characters:
        return graph

    # Find protagonist by number of relations pointing to them + their own relations
    freq: Counter = Counter()
    for ch in characters:
        freq[ch.get("name", "")] += len(ch.get("relations", []))
        for rel in ch.get("relations", []):
            freq[rel.get("target", "")] += 1
    if not freq:
        return graph
    protagonist = freq.most_common(1)[0][0]

    # Count how many other characters have a direct relation to/from each character
    mention_count: Counter = Counter()
    for ch in characters:
        name = ch.get("name", "")
        mention_count[name] += len(ch.get("relations", []))
        for rel in ch.get("relations", []):
            mention_count[rel.get("target", "")] += 1

    keep_names = {name for name, cnt in mention_count.items() if cnt >= MIN_APPEARANCES}
    keep_names.add(protagonist)

    filtered_chars = [c for c in characters if c.get("name") in keep_names]
    return {**graph, "characters": filtered_chars}


_ARCHIVE_LIST_SECTIONS = {
    "characters",
    "events",
    "supporting_characters",
    "relationship_states",
    "asset_accounts",
    "transaction_ledger",
    "item_custody",
    "timeline",
    "knowledge_boundaries",
    "commitments",
    "plot_threads",
    "canon_facts",
}
_ARCHIVE_DICT_SECTIONS = {"protagonist", "dialogue_profiles"}


def _json_dict(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def _json_list(raw: str | None) -> list:
    try:
        value = json.loads(raw or "[]")
        return value if isinstance(value, list) else []
    except (TypeError, ValueError):
        return []


def _validate_archive_section(section: str, data: Any) -> None:
    if section in _ARCHIVE_LIST_SECTIONS:
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{section} 必须是由对象组成的列表",
            )
    elif section in _ARCHIVE_DICT_SECTIONS:
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{section} 必须是对象",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持编辑的档案分类：{section}",
        )

    if section == "canon_facts":
        for index, item in enumerate(data):
            if not str(item.get("fact") or "").strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"第 {index + 1} 条不可逆事实缺少 fact 内容",
                )


def _archive_payload(novel) -> dict:
    facts = normalize_canon_facts(_json_list(novel.canon_facts))
    ledger = normalize_state_ledger(
        _json_dict(novel.state_ledger),
        facts,
        current_chapter=int(_json_dict(novel.state_ledger).get("current_chapter") or 0),
    )
    # The archive is an editing surface, so it must expose every stored node.
    # Filtering is only appropriate for the legacy visualization endpoint;
    # otherwise a manually added minor character could disappear immediately.
    graph = _json_dict(novel.knowledge_graph)
    return {
        "current_chapter": int(ledger.get("current_chapter") or 0),
        "time_place": ledger.get("time_place", ""),
        "protagonist": ledger.get("protagonist", {}),
        "characters": graph.get("characters", []),
        "events": graph.get("events", []),
        "supporting_characters": ledger.get("supporting_characters", []),
        "relationship_states": ledger.get("relationship_states", []),
        "dialogue_profiles": ledger.get("dialogue_profiles", {}),
        "asset_accounts": ledger.get("asset_accounts", []),
        "transaction_ledger": ledger.get("transaction_ledger", []),
        "item_custody": ledger.get("item_custody", []),
        "timeline": ledger.get("timeline", []),
        "knowledge_boundaries": ledger.get("knowledge_boundaries", []),
        "commitments": ledger.get("commitments", []),
        "plot_threads": ledger.get("plot_threads", []),
        "canon_facts": facts,
        "manual_edit_history": ledger.get("manual_edit_history", []),
    }


class KnowledgeGraphService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.novel_repo = NovelRepository(db)
        self.chapter_repo = ChapterRepository(db)
        self.content_repo = ChapterContentRepository(db)
        self.ai_config_repo = AIConfigRepository(db)

    async def update_graph_from_chapter(self, novel_id: int, chapter_id: int, owner_id: int) -> dict:
        """Update graph using the latest content of a specific chapter."""
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        from app.repositories.chapter_repo import ChapterRepository
        chapter = await ChapterRepository(self.db).get(chapter_id)
        if not chapter or chapter.novel_id != novel_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

        content_obj = await self.content_repo.get_latest(chapter_id)
        if not content_obj or not content_obj.content:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Chapter has no content")

        ai_config = None
        if novel.ai_config_id:
            ai_config = await self.ai_config_repo.get(novel.ai_config_id)
        if not ai_config:
            ai_config = await self.ai_config_repo.get_default()

        # Filter existing graph before passing to AI so stale characters don't get carried forward
        existing_graph_raw = novel.knowledge_graph or ""
        if existing_graph_raw:
            try:
                existing_graph_raw = json.dumps(
                    _filter_graph(json.loads(existing_graph_raw)), ensure_ascii=False
                )
            except Exception:
                pass

        new_graph = await ai_service.update_knowledge_graph(
            chapter_content=content_obj.content,
            chapter_number=chapter.chapter_number,
            chapter_title=chapter.title,
            existing_graph=existing_graph_raw,
            ai_config=ai_config,
        )
        try:
            filtered = _filter_graph(json.loads(new_graph))
            new_graph = json.dumps(filtered, ensure_ascii=False)
        except Exception:
            pass
        await self.novel_repo.update(novel, knowledge_graph=new_graph)
        await self.db.commit()

        try:
            return json.loads(new_graph)
        except Exception:
            return {"characters": [], "events": []}

    async def get_chapters_with_content(self, novel_id: int, owner_id: int) -> list:
        """Return list of chapter ids/numbers that have content, sorted by chapter_number."""
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
        chapters = await self.chapter_repo.get_by_novel(novel_id)
        chapters.sort(key=lambda c: c.chapter_number)
        result = []
        for ch in chapters:
            content_obj = await self.content_repo.get_latest(ch.id)
            if content_obj and content_obj.content:
                result.append({"id": ch.id, "chapter_number": ch.chapter_number, "title": ch.title})
        return result

    async def clear_graph(self, novel_id: int, owner_id: int) -> dict:
        """Clear the knowledge graph."""
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
        await self.novel_repo.update(novel, knowledge_graph=None)
        await self.db.commit()
        return {"characters": [], "events": []}

    async def get_graph(self, novel_id: int, owner_id: int) -> dict:
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
        if not novel.knowledge_graph:
            return {"characters": [], "events": []}
        try:
            return _filter_graph(json.loads(novel.knowledge_graph))
        except Exception:
            return {"characters": [], "events": []}

    async def get_archive(self, novel_id: int, owner_id: int) -> dict:
        """Return every continuity record used by later chapter generation."""
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
        return _archive_payload(novel)

    async def update_archive_section(
        self,
        novel_id: int,
        section: str,
        data: Any,
        owner_id: int,
    ) -> dict:
        """Replace one archive section after validation and normalization.

        Manual edits are written to the authoritative state_ledger/canon_facts
        fields consumed by the generation workflow, not merely to a display
        copy of the old relationship graph.
        """
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
        _validate_archive_section(section, data)

        graph = _json_dict(novel.knowledge_graph)
        facts = normalize_canon_facts(_json_list(novel.canon_facts))
        raw_ledger = _json_dict(novel.state_ledger)
        ledger = normalize_state_ledger(
            raw_ledger,
            facts,
            current_chapter=int(raw_ledger.get("current_chapter") or 0),
        )

        before = (
            graph.get(section)
            if section in {"characters", "events"}
            else facts if section == "canon_facts"
            else ledger.get(section)
        )
        before_hash = hashlib.sha256(
            json.dumps(before, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        after_hash = hashlib.sha256(
            json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]

        if section in {"characters", "events"}:
            graph[section] = data
        elif section == "canon_facts":
            facts = normalize_canon_facts(data)
        else:
            ledger[section] = data

        ledger = normalize_state_ledger(
            ledger,
            facts,
            current_chapter=int(ledger.get("current_chapter") or 0),
        )
        history = ledger.get("manual_edit_history")
        if not isinstance(history, list):
            history = []
        history.append({
            "section": section,
            "edited_at": datetime.now(timezone.utc).isoformat(),
            "before_hash": before_hash,
            "after_hash": after_hash,
            "source": "desktop_manual_edit",
        })
        ledger["manual_edit_history"] = history[-200:]

        # Keep the legacy graph screen and generation continuity mirror in sync.
        graph["continuity"] = ledger
        graph["events"] = graph.get("events", [])

        await self.novel_repo.update(
            novel,
            knowledge_graph=json.dumps(graph, ensure_ascii=False),
            state_ledger=json.dumps(ledger, ensure_ascii=False),
            canon_facts=json.dumps(facts, ensure_ascii=False),
        )
        await self.db.commit()
        return _archive_payload(novel)

    async def rebuild_graph(self, novel_id: int, owner_id: int) -> dict:
        """Rebuild graph from scratch by processing all chapters with content.
        Each chapter is extracted independently, then all results are merged in code."""
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        ai_config = None
        if novel.ai_config_id:
            ai_config = await self.ai_config_repo.get(novel.ai_config_id)
        if not ai_config:
            ai_config = await self.ai_config_repo.get_default()

        chapters = await self.chapter_repo.get_by_novel(novel_id)
        chapters.sort(key=lambda c: c.chapter_number)

        # Extract each chapter independently (no existing_graph), then merge
        char_map: dict[str, dict] = {}  # name -> latest character info

        for chapter in chapters:
            content_obj = await self.content_repo.get_latest(chapter.id)
            if not content_obj or not content_obj.content:
                continue
            try:
                raw = await ai_service.update_knowledge_graph(
                    chapter_content=content_obj.content,
                    chapter_number=chapter.chapter_number,
                    chapter_title=chapter.title,
                    existing_graph="",  # extract independently
                    ai_config=ai_config,
                )
                parsed = json.loads(raw)
                for ch in parsed.get("characters", []):
                    name = ch.get("name")
                    if name:
                        char_map[name] = ch  # later chapters overwrite with updated info
            except Exception as e:
                logger.warning(f"Graph update failed for chapter {chapter.chapter_number}: {e}")

        merged = {"characters": list(char_map.values())}
        filtered = _filter_graph(merged)
        current_graph = json.dumps(filtered, ensure_ascii=False)

        await self.novel_repo.update(novel, knowledge_graph=current_graph)
        await self.db.commit()
        return filtered
