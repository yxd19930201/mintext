import json
import logging
from datetime import datetime, timezone
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
from app.services.ai_service import ai_service
from app.services.novel_skill_service import novel_skill_prompt
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


def _json_value(raw: str | None, default):
    if not raw:
        return default
    try:
        value = json.loads(raw)
        return value
    except (TypeError, json.JSONDecodeError):
        return default


def _audit_entry(kind: str, chapter_range: str, approved: bool, attempts: int, issues: list) -> dict:
    return {
        "kind": kind,
        "chapter_range": chapter_range,
        "approved": approved,
        "attempts": attempts,
        "issues": issues,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def _normalize_outline_chapters(candidate: list[dict], revised: list[dict] | None = None) -> list[dict]:
    """Merge an AI audit revision onto the original batch without losing required fields."""
    revised = revised or []
    revised_by_number = {
        item.get("chapter_number"): item
        for item in revised
        if isinstance(item, dict) and isinstance(item.get("chapter_number"), int)
    }
    normalized: list[dict] = []
    for index, original in enumerate(candidate):
        if not isinstance(original, dict):
            continue
        chapter_number = original.get("chapter_number")
        patch = revised_by_number.get(chapter_number)
        if patch is None and index < len(revised) and isinstance(revised[index], dict):
            indexed = revised[index]
            if indexed.get("chapter_number") in (None, chapter_number):
                patch = indexed
        merged = dict(original)
        if patch:
            merged.update({key: value for key, value in patch.items() if value is not None})
        merged["chapter_number"] = chapter_number
        merged["title"] = str(merged.get("title") or original.get("title") or f"第{chapter_number}章").strip()
        merged["synopsis"] = str(
            merged.get("synopsis") or original.get("synopsis") or "承接前章并推进本阶段主线。"
        ).strip()
        merged.setdefault("before_state", {})
        merged.setdefault("after_state", {})
        merged.setdefault("irreversible_facts", [])
        normalized.append(merged)
    return normalized


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

        ai_config = None
        if req.ai_config_id:
            ai_config = await self.ai_config_repo.get(req.ai_config_id)
            if not ai_config:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")
        elif novel.ai_config_id:
            ai_config = await self.ai_config_repo.get(novel.ai_config_id)
        if not ai_config:
            ai_config = await self.ai_config_repo.get_default()

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
            }
        canon_facts = _json_value(novel.canon_facts, [])
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
        candidate_chapters = _normalize_outline_chapters(outline_data.get("chapters", []))
        last_issues: list = []
        approved = False
        attempts = 0
        for attempts in range(1, 4):
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
            last_issues = audit.get("issues") or []
            revised = audit.get("revised_chapters") or []
            if audit.get("approved") is True:
                candidate_chapters = _normalize_outline_chapters(candidate_chapters, revised)
                approved = True
                break
            if revised:
                candidate_chapters = _normalize_outline_chapters(candidate_chapters, revised)
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
        # Get chapter and verify ownership
        chapter = await self.chapter_repo.get(chapter_id)
        if not chapter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chapter not found")

        novel = await self.novel_repo.get_by_id_and_owner(chapter.novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        # Get AI config
        ai_config = None
        if req.ai_config_id:
            ai_config = await self.ai_config_repo.get(req.ai_config_id)
            if not ai_config:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")
        elif novel.ai_config_id:
            ai_config = await self.ai_config_repo.get(novel.ai_config_id)
        if not ai_config:
            ai_config = await self.ai_config_repo.get_default()

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
            }
        canon_facts = _json_value(novel.canon_facts, [])
        audit_log = _json_value(novel.continuity_audits, [])

        # Build context
        context_parts = []
        context_parts.append(f"小说：{novel.title}\n故事大概：{novel.synopsis}")
        context_parts.append(
            "【固定全书阶段路线图】\n"
            + json.dumps(roadmap, ensure_ascii=False)
            + "\n【当前正史人物、身份与资产账本】\n"
            + json.dumps(state_ledger, ensure_ascii=False)
            + "\n【不可逆正史事实】\n"
            + json.dumps(canon_facts[-100:], ensure_ascii=False)
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
        prompt += "请在 2800 到 3200 字以内完整交代本章剧情，情节完整自然收尾，不要超过 3200 字。"

        # Generate content
        content = await ai_service.generate_chapter(
            prompt=prompt,
            context="\n\n".join(context_parts),
            system_prompt=req.system_prompt or novel.system_prompt,
            ai_config=ai_config,
        )

        chapter_outline = {
            "chapter_number": chapter.chapter_number,
            "title": chapter.title,
            "synopsis": chapter.synopsis or "",
        }
        if novel.outline:
            outline_data = _json_value(novel.outline, {})
            chapter_outline = next(
                (
                    item
                    for item in outline_data.get("chapters", [])
                    if item.get("chapter_number") == chapter.chapter_number
                ),
                chapter_outline,
            )

        # Skill gate: reject -> automatically rewrite -> review again.
        # Nothing is persisted until a review returns approved=true.
        approved = False
        last_issues: list = []
        attempts = 0
        full_context = "\n\n".join(context_parts)
        for attempts in range(1, 4):
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
            last_issues = audit.get("issues") or []
            if audit.get("approved") is True:
                approved = True
                break
            content = await ai_service.revise_chapter_candidate(
                original_content=content,
                issues=last_issues,
                context=full_context,
                prompt=prompt,
                ai_config=ai_config,
            )
        audit_log.append(
            _audit_entry(
                "draft",
                str(chapter.chapter_number),
                approved,
                attempts,
                last_issues,
            )
        )
        if not approved:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "message": "正文连续性审核未通过，已自动返修 3 次，未写入数据库",
                    "issues": last_issues,
                },
            )

        # Review passed. Build the post-chapter canon update before saving, so
        # content and ledger/facts enter the database in the same transaction.
        canon_update = await ai_service.extract_canon_update(
            chapter_number=chapter.chapter_number,
            chapter_title=chapter.title,
            content=content,
            existing_ledger=state_ledger,
            existing_facts=canon_facts,
            ai_config=ai_config,
        )
        updated_ledger = canon_update.get("state_ledger")
        if not isinstance(updated_ledger, dict) or not updated_ledger:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="正文已通过审核，但 AI 未返回有效状态账本；本章未保存",
            )
        new_facts = canon_update.get("new_irreversible_facts") or []
        existing_fact_keys = {
            (item.get("chapter"), item.get("type"), item.get("fact"))
            for item in canon_facts
            if isinstance(item, dict)
        }
        for fact in new_facts:
            if not isinstance(fact, dict):
                continue
            key = (fact.get("chapter"), fact.get("type"), fact.get("fact"))
            if key not in existing_fact_keys:
                canon_facts.append(fact)
                existing_fact_keys.add(key)

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

        return GenerateChapterResult(
            chapter_id=chapter_id,
            content_id=chapter_content.id,
            content=content,
            word_count=word_count,
        )

    async def batch_generate_chapters(
        self, novel_id: int, req: BatchGenerateChaptersRequest, owner_id: int
    ) -> BatchGenerateResult:
        # Verify novel ownership
        novel = await self.novel_repo.get_by_id_and_owner(novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")

        # Validate configuration before entering the per-chapter error loop so
        # the UI can show one actionable "configure AI" message.
        ai_config = None
        if req.ai_config_id:
            ai_config = await self.ai_config_repo.get(req.ai_config_id)
            if not ai_config:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")
        elif novel.ai_config_id:
            ai_config = await self.ai_config_repo.get(novel.ai_config_id)
        if not ai_config:
            ai_config = await self.ai_config_repo.get_default()
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
                        ai_config_id=req.ai_config_id,
                        system_prompt=req.system_prompt,
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

        # Get AI config
        ai_config = None
        if req.ai_config_id:
            ai_config = await self.ai_config_repo.get(req.ai_config_id)
            if not ai_config:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")
        elif novel.ai_config_id:
            ai_config = await self.ai_config_repo.get(novel.ai_config_id)
        if not ai_config:
            ai_config = await self.ai_config_repo.get_default()

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
        canon_facts = _json_value(novel.canon_facts, [])
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
        candidate = [{
            "chapter_number": last_chapter.chapter_number + 1,
            "title": next_chapter_data["title"],
            "synopsis": next_chapter_data.get("synopsis", ""),
        }]
        previous_outline = _json_value(novel.outline, {}).get("chapters", [])
        approved = False
        last_issues: list = []
        attempts = 0
        for attempts in range(1, 4):
            audit = await ai_service.audit_outline_candidate(
                synopsis=novel.synopsis,
                roadmap=roadmap,
                state_ledger=state_ledger,
                canon_facts=canon_facts,
                previous_chapters=previous_outline,
                candidate_chapters=candidate,
                ai_config=ai_config,
            )
            last_issues = audit.get("issues") or []
            revised = audit.get("revised_chapters") or []
            if audit.get("approved") is True:
                candidate = revised or candidate
                approved = True
                break
            if revised:
                candidate = revised
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
                ai_config_id=req.ai_config_id,
                system_prompt=req.system_prompt,
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
