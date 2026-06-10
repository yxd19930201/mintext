import json
import logging
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

        try:
            outline_json = await ai_service.generate_novel_outline(
                title=novel.title,
                genre=novel.genre,
                synopsis=novel.synopsis,
                total_chapters=req.total_chapters,
                start_chapter=req.start_chapter,
                end_chapter=end_chapter,
                theme=req.theme or "",
                system_prompt=req.system_prompt or novel.system_prompt,
                ai_config=ai_config,
            )
            logger.info(f"generate_novel_outline success, json length={len(outline_json)}")
        except Exception as e:
            logger.error(f"generate_novel_outline failed: {e}", exc_info=True)
            raise

        outline_data = json.loads(outline_json)

        # Merge into existing outline stored on novel (append new chapters)
        existing_chapters: list = []
        existing_theme = ""
        if novel.outline:
            try:
                existing = json.loads(novel.outline)
                existing_chapters = existing.get("chapters", [])
                existing_theme = existing.get("theme", "")
            except Exception:
                pass

        new_chapters = outline_data.get("chapters", [])
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
        novel = await self.novel_repo.update(novel, outline=json.dumps(merged_outline, ensure_ascii=False),
                                             total_chapters=req.total_chapters)
        await self.db.commit()

        chapters = [
            ChapterOutlineItem(
                chapter_number=ch["chapter_number"],
                title=ch["title"],
                synopsis=ch["synopsis"],
            )
            for ch in new_chapters
        ]

        return OutlineResult(
            total_chapters=req.total_chapters,
            theme=merged_theme,
            chapters=chapters,
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

        # Build context
        context_parts = []
        context_parts.append(f"小说：{novel.title}\n故事大概：{novel.synopsis}")

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
                    context_parts.append("\n".join(kg_lines))
            except Exception:
                pass

        # KEY LOGIC: Get previous chapter ending for continuity
        if chapter.chapter_number > 1:
            prev_chapter = await self.chapter_repo.get_by_number(novel.id, chapter.chapter_number - 1)
            if prev_chapter:
                prev_content = await self.content_repo.get_latest(prev_chapter.id)
                if prev_content and prev_content.content:
                    # Take last 800 characters for context
                    snippet = prev_content.content[-800:]
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

        # Count words
        word_count = len(content)

        # Upsert chapter content
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

        await self.db.commit()

        # Async update knowledge graph in background (non-blocking, best-effort)
        try:
            new_graph = await ai_service.update_knowledge_graph(
                chapter_content=content,
                chapter_number=chapter.chapter_number,
                chapter_title=chapter.title,
                existing_graph=novel.knowledge_graph or "",
                ai_config=ai_config,
            )
            await self.novel_repo.update(novel, knowledge_graph=new_graph)
            await self.db.commit()
        except Exception:
            pass  # graph update failure must not break chapter generation

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

        # Extract last 1000 characters for context
        snippet = last_content.content[-1000:]

        # Generate next chapter outline
        sys_msg = "你是一位专业的网络小说作家。请根据上一章内容，生成下一章的标题和简介。严格按照 JSON 格式输出。"
        user_msg = (
            f"小说：{novel.title}\n"
            f"故事大概：{novel.synopsis}\n\n"
            f"上一章（第 {last_chapter.chapter_number} 章：{last_chapter.title}）结尾内容：\n{snippet}\n\n"
            f"请生成第 {last_chapter.chapter_number + 1} 章的标题和简介，以纯 JSON 格式返回：\n"
            '{"title": "章节标题", "synopsis": "本章简介"}'
        )

        from app.services.ai_service import ai_service
        base_url, api_key, model = ai_service._resolve(ai_config)
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await ai_service._call(messages, base_url, api_key, model, json_mode=True)

        # Parse response
        try:
            next_chapter_data = json.loads(raw.strip())
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to parse next chapter JSON")

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
