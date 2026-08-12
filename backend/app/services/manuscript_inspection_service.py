from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from statistics import mean, pstdev

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.ai_config_repo import AIConfigRepository
from app.repositories.chapter_content_repo import ChapterContentRepository
from app.repositories.chapter_repo import ChapterRepository
from app.repositories.manuscript_report_repo import ManuscriptReportRepository
from app.repositories.novel_repo import NovelRepository
from app.schemas.manuscript_inspection import ManuscriptInspectionRequest
from app.services.ai_service import ai_service
from app.services.generation_mode_service import resolve_generation_config


_AI_STYLE_MARKERS = (
    "值得注意的是", "毋庸置疑", "总而言之", "综上所述", "与此同时", "然而",
    "不禁", "仿佛", "似乎在诉说", "空气中弥漫着", "眼神中闪过", "嘴角勾起一抹",
    "深吸一口气", "缓缓开口", "心中暗道", "这一刻", "这不仅", "更是",
    "命运的齿轮", "前所未有", "某种意义上",
)


def _clean_text(value: str) -> str:
    return (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _clamp_score(value, default: float = 0) -> float:
    try:
        return round(max(0.0, min(100.0, float(value))), 1)
    except (TypeError, ValueError):
        return default


def _text_metrics(text: str) -> dict:
    compact = re.sub(r"\s+", "", text)
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n+", text) if item.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [item.strip() for item in text.splitlines() if item.strip()]
    sentences = [
        item.strip() for item in re.split(r"(?<=[。！？?!])", compact) if item.strip()
    ]
    sentence_lengths = [len(item) for item in sentences]
    sentence_counts = Counter(item for item in sentences if 12 <= len(item) <= 160)
    duplicates = [
        {"text": value[:100], "count": count}
        for value, count in sentence_counts.most_common(12) if count > 1
    ]
    marker_counts = [
        {"pattern": marker, "count": text.count(marker)}
        for marker in _AI_STYLE_MARKERS if text.count(marker)
    ]
    marker_counts.sort(key=lambda item: item["count"], reverse=True)
    dialogue_chars = sum(len(value) for value in re.findall(r"[“\"]([^”\"]{1,1000})[”\"]", text, re.S))
    chapter_headings = re.findall(
        r"(?m)^\s*(?:#{1,3}\s*)?第\s*([0-9一二三四五六七八九十百千零〇两]+)\s*[章节回]\s*[:：]?\s*(.*)$",
        text,
    )
    return {
        "character_count": len(compact),
        "paragraph_count": len(paragraphs),
        "sentence_count": len(sentences),
        "chapter_heading_count": len(chapter_headings),
        "average_sentence_length": round(mean(sentence_lengths), 1) if sentence_lengths else 0,
        "sentence_length_stddev": round(pstdev(sentence_lengths), 1) if len(sentence_lengths) > 1 else 0,
        "dialogue_ratio_percent": round(dialogue_chars / max(len(compact), 1) * 100, 1),
        "duplicate_sentence_count": sum(item["count"] - 1 for item in duplicates),
        "repeated_sentences": duplicates,
        "ai_style_marker_total": sum(item["count"] for item in marker_counts),
        "ai_style_markers": marker_counts[:15],
    }


def _representative_sample(text: str, max_chars: int = 32000) -> str:
    """Legacy helper retained for tests and short-text diagnostics."""
    if len(text) <= max_chars:
        return text
    segment_size = max_chars // 6
    last_start = max(len(text) - segment_size, 0)
    starts = [0, int(len(text) * .2), int(len(text) * .4), int(len(text) * .6), int(len(text) * .8), last_start]
    parts = []
    for index, start in enumerate(starts, 1):
        start = min(max(start, 0), last_start)
        parts.append(
            f"【抽样片段 {index}/6，原文位置约 {round(start / len(text) * 100)}%】\n"
            f"{text[start:start + segment_size].strip()}"
        )
    return "\n\n".join(parts)


def _group_documents(documents: list[dict], max_chars: int = 28000) -> list[list[dict]]:
    """Keep every chapter intact where possible and cover every input document."""
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for document in documents:
        size = len(document["content"])
        if current and current_chars + size > max_chars:
            groups.append(current)
            current = []
            current_chars = 0
        current.append(document)
        current_chars += size
        if size >= max_chars:
            groups.append(current)
            current = []
            current_chars = 0
    if current:
        groups.append(current)
    return groups


def _report_sources(inspection_type: str) -> list[dict]:
    sources = [{
        "name": "oh-story-claudecode / story-review & story-deslop",
        "url": "https://github.com/worldwonderer/oh-story-claudecode",
        "license": "MIT",
    }]
    if inspection_type == "quality":
        sources.append({
            "name": "howells/fiction / full manuscript critique",
            "url": "https://github.com/howells/fiction",
            "license": "MIT",
        })
    else:
        sources.extend([
            {"name": "harshaneel/humanize / ai-check", "url": "https://github.com/harshaneel/humanize", "license": "MIT"},
            {"name": "stephenturner/skill-deslop", "url": "https://github.com/stephenturner/skill-deslop", "license": "MIT"},
        ])
    return sources


class ManuscriptInspectionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.novel_repo = NovelRepository(db)
        self.chapter_repo = ChapterRepository(db)
        self.content_repo = ChapterContentRepository(db)
        self.ai_config_repo = AIConfigRepository(db)
        self.report_repo = ManuscriptReportRepository(db)

    async def _documents(self, req: ManuscriptInspectionRequest, owner_id: int) -> tuple[str, list[dict], dict]:
        if req.source_documents:
            documents = [
                {
                    "name": item.name,
                    "chapter_number": item.chapter_number or index,
                    "content": _clean_text(item.content),
                }
                for index, item in enumerate(req.source_documents, 1)
            ]
            return (req.source_name or "导入小说文件夹").strip(), documents, {}
        if req.source_text:
            return (req.source_name or "导入小说").strip(), [{
                "name": req.source_name or "导入文本",
                "chapter_number": 1,
                "content": _clean_text(req.source_text),
            }], {}

        novel = await self.novel_repo.get_by_id_and_owner(req.novel_id, owner_id)
        if not novel:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="小说项目不存在")
        documents = []
        chapters = await self.chapter_repo.get_by_novel(novel.id)
        for chapter in sorted(chapters, key=lambda item: item.chapter_number):
            content = await self.content_repo.get_latest(chapter.id)
            body = _clean_text(content.content if content else "")
            if body:
                documents.append({
                    "name": f"第{chapter.chapter_number}章 {chapter.title}",
                    "chapter_number": chapter.chapter_number,
                    "content": body,
                })
        if not documents:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="该小说尚无可体检的章节正文")
        context = {
            "title": novel.title,
            "genre": novel.genre or "未分类",
            "synopsis": novel.synopsis,
            "outline": (novel.outline or "")[:16000],
        }
        return novel.title, documents, context

    async def _ai_config(self, req: ManuscriptInspectionRequest):
        return await resolve_generation_config(
            self.ai_config_repo,
            req,
            explicit_config_id=req.ai_config_id,
        )

    @staticmethod
    def _fingerprint(inspection_type: str, documents: list[dict]) -> str:
        digest = hashlib.sha256(inspection_type.encode("utf-8"))
        for document in documents:
            digest.update(document["name"].encode("utf-8"))
            digest.update(b"\0")
            digest.update(document["content"].encode("utf-8"))
            digest.update(b"\0")
        return digest.hexdigest()

    async def _resumable(self, owner_id: int, inspection_type: str, fingerprint: str):
        for entity in await self.report_repo.list_by_owner(owner_id, limit=50):
            if entity.inspection_type != inspection_type:
                continue
            try:
                report = json.loads(entity.report_json)
            except Exception:
                continue
            if report.get("source_fingerprint") == fingerprint and report.get("status") in {"running", "failed"}:
                return entity, report
        return None, None

    @staticmethod
    def _batch_prompts(inspection_type: str, documents: list[dict], context: dict, batch_number: int, total_batches: int) -> tuple[str, str]:
        if inspection_type == "quality":
            system = (
                "你是中文长篇小说逐章审稿编辑。必须完整阅读本批次提供的每一章，不得抽样。"
                "逐章检查结构作用、人物行为、前后逻辑、时间线、资产数字、节奏、情绪、对话和语言。"
                "每个问题必须引用原文章节和短证据。只返回合法 JSON。"
            )
            score_note = "score 是章节质量分，越高越好"
        else:
            system = (
                "你是中文小说文体审稿编辑。必须完整阅读本批次每一章，不得抽样。"
                "逐章检查模板句、机械节奏、过度解释、角色同声、重复表达、抽象空话和缺乏具体感。"
                "这只是文体风险评估，不得声称能鉴定作者身份。每项判断必须引用原文。只返回合法 JSON。"
            )
            score_note = "score 是疑似 AI 文体风险分，越高风险越高"
        payload = [{
            "document_name": item["name"],
            "chapter_number": item["chapter_number"],
            "metrics": _text_metrics(item["content"]),
            "full_text": item["content"],
        } for item in documents]
        contract = {
            "batch_summary": "本批次概括",
            "chapter_reviews": [{
                "document_name": "必须与输入文件名一致",
                "chapter_number": 1,
                "score": 0,
                "summary": "本章评价",
                "strengths": [],
                "issues": [{"severity": "high|medium|low", "evidence": "原文短句", "issue": "问题", "suggestion": "建议"}],
            }],
            "cross_chapter_findings": [],
        }
        user = (
            f"全书背景：{json.dumps(context, ensure_ascii=False)}\n"
            f"当前为第 {batch_number}/{total_batches} 批，共 {len(documents)} 章。{score_note}。\n"
            "chapter_reviews 必须与输入章节一一对应，数量和 document_name 都必须完全一致。\n"
            f"输出契约：{json.dumps(contract, ensure_ascii=False)}\n\n"
            f"本批全部章节（full_text 均须完整阅读）：{json.dumps(payload, ensure_ascii=False)}"
        )
        return system, user

    @staticmethod
    def _aggregate_prompts(inspection_type: str, source_name: str, context: dict, metrics: dict, batch_results: list[dict]) -> tuple[str, str]:
        if inspection_type == "quality":
            system = (
                "你是长篇小说总编。根据已经逐章完整检查的阶段报告，进行全书结构、人物弧线、逻辑连续性、"
                "节奏、情绪、对话、语言和追读力总评。不要虚构阶段报告中没有的问题。只返回合法 JSON。"
            )
            dimensions = "结构与主线、人物塑造、逻辑连续性、节奏、情绪张力、对话、语言质感、追读力"
            score_note = "overall_score 是质量分，越高越好"
        else:
            system = (
                "你是长篇小说文体总编。根据逐章完整检查结果，汇总模板化、机械化和角色同声等风险。"
                "不得把风格风险说成 AI 作者身份鉴定。只返回合法 JSON。"
            )
            dimensions = "节奏突发性、结构模板化、抽象空话、过度解释、连接词、重复修辞、标点模式、角色声音、具体感"
            score_note = "overall_score 是疑似 AI 文体风险分，越高风险越高"
        contract = {
            "overall_score": 0,
            "verdict": "一句话结论",
            "summary": "全书总评",
            "dimensions": [{"name": "维度", "score": 0, "findings": [], "suggestions": []}],
            "critical_issues": [{"severity": "high|medium|low", "location": "章节", "issue": "问题", "evidence": "证据", "suggestion": "建议"}],
            "strengths": [],
            "prioritized_actions": [],
        }
        user = (
            f"作品：{source_name}\n全书背景：{json.dumps(context, ensure_ascii=False)}\n"
            f"全书本地统计：{json.dumps(metrics, ensure_ascii=False)}\n"
            f"必须覆盖维度：{dimensions}；{score_note}。\n"
            f"输出契约：{json.dumps(contract, ensure_ascii=False)}\n\n"
            f"逐章阶段报告：{json.dumps(batch_results, ensure_ascii=False)}"
        )
        return system, user

    async def inspect(self, req: ManuscriptInspectionRequest, owner_id: int) -> dict:
        source_name, documents, context = await self._documents(req, owner_id)
        full_text = "\n\n".join(f"{item['name']}\n{item['content']}" for item in documents)
        metrics = _text_metrics(full_text)
        groups = _group_documents(documents)
        fingerprint = self._fingerprint(req.inspection_type, documents)
        entity, progress = await self._resumable(owner_id, req.inspection_type, fingerprint)
        if not entity:
            progress = {
                "status": "running",
                "source_fingerprint": fingerprint,
                "overall_score": 0,
                "verdict": "正在逐章完整体检",
                "summary": "体检任务已建立，正在按章节顺序检查全部正文。",
                "progress": {"completed_chapters": 0, "total_chapters": len(documents), "completed_batches": 0, "total_batches": len(groups)},
                "batch_results": {},
            }
            entity = await self.report_repo.create(
                owner_id=owner_id,
                novel_id=req.novel_id,
                inspection_type=req.inspection_type,
                source_name=source_name,
                word_count=metrics["character_count"],
                report_json=json.dumps(progress, ensure_ascii=False),
            )
            await self.db.commit()
        else:
            progress["status"] = "running"
            progress["verdict"] = "正在从上次检查点继续体检"
            progress.pop("error", None)
            await self.report_repo.update(entity, report_json=json.dumps(progress, ensure_ascii=False))
            await self.db.commit()

        ai_config = await self._ai_config(req)
        try:
            batch_results = dict(progress.get("batch_results") or {})
            completed_chapters = sum(len(groups[int(key)]) for key in batch_results if str(key).isdigit() and int(key) < len(groups))
            for index, group in enumerate(groups):
                key = str(index)
                if key in batch_results:
                    continue
                system_prompt, user_prompt = self._batch_prompts(req.inspection_type, group, context, index + 1, len(groups))
                result = await ai_service.analyze_structured_text(system_prompt, user_prompt, ai_config, max_tokens=7000)
                reviews = result.get("chapter_reviews")
                if not isinstance(reviews, list) or len(reviews) < len(group):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"第 {index + 1} 批逐章报告不完整：应返回 {len(group)} 章，实际返回 {len(reviews or [])} 章。已保存前序检查点，可继续体检。",
                    )
                batch_results[key] = result
                completed_chapters += len(group)
                progress.update({
                    "status": "running",
                    "verdict": f"已完整检查 {completed_chapters}/{len(documents)} 章",
                    "batch_results": batch_results,
                    "progress": {
                        "completed_chapters": completed_chapters,
                        "total_chapters": len(documents),
                        "completed_batches": len(batch_results),
                        "total_batches": len(groups),
                    },
                })
                await self.report_repo.update(entity, report_json=json.dumps(progress, ensure_ascii=False))
                await self.db.commit()

            ordered_results = [batch_results[str(index)] for index in range(len(groups))]
            system_prompt, user_prompt = self._aggregate_prompts(
                req.inspection_type, source_name, context, metrics, ordered_results,
            )
            report = await ai_service.analyze_structured_text(system_prompt, user_prompt, ai_config, max_tokens=7000)
            report["overall_score"] = _clamp_score(report.get("overall_score"))
            report.setdefault("verdict", "体检完成")
            report.setdefault("summary", "")
            report.setdefault("dimensions", [])
            report.setdefault("prioritized_actions", [])
            report.update({
                "status": "completed",
                "inspection_type": req.inspection_type,
                "source_name": source_name,
                "source_fingerprint": fingerprint,
                "local_metrics": metrics,
                "progress": {"completed_chapters": len(documents), "total_chapters": len(documents), "completed_batches": len(groups), "total_batches": len(groups)},
                "chapter_reviews": [review for result in ordered_results for review in result.get("chapter_reviews", [])],
                "cross_chapter_findings": [finding for result in ordered_results for finding in result.get("cross_chapter_findings", [])],
                "methodology": "全部章节正文均按文件/数据库章节顺序分批完整送检；每批报告先落库，再基于全部阶段结果生成全书总评。未使用代表性抽样代替正文检查。",
                "sources": _report_sources(req.inspection_type),
            })
            if req.inspection_type == "ai_trace":
                report["disclaimer"] = "本报告评估模板化和机械化文体风险，不是作者身份鉴定，也不能证明文字一定由 AI 生成。"
            await self.report_repo.update(entity, report_json=json.dumps(report, ensure_ascii=False))
            await self.db.commit()
            return self._read(entity)
        except Exception as exc:
            progress["status"] = "failed"
            progress["verdict"] = "体检中断，可从已保存章节继续"
            progress["error"] = getattr(exc, "detail", None) or str(exc)
            await self.report_repo.update(entity, report_json=json.dumps(progress, ensure_ascii=False))
            await self.db.commit()
            raise

    @staticmethod
    def _read(entity) -> dict:
        try:
            report = json.loads(entity.report_json)
        except (TypeError, json.JSONDecodeError):
            report = {}
        return {
            "id": entity.id,
            "inspection_type": entity.inspection_type,
            "source_name": entity.source_name,
            "novel_id": entity.novel_id,
            "word_count": entity.word_count,
            "report": report,
            "created_at": entity.created_at,
        }

    async def list_reports(self, owner_id: int) -> list[dict]:
        summaries = []
        for entity in await self.report_repo.list_by_owner(owner_id):
            item = self._read(entity)
            report = item["report"]
            progress = report.get("progress") or {}
            summaries.append({
                "id": entity.id,
                "inspection_type": entity.inspection_type,
                "source_name": entity.source_name,
                "novel_id": entity.novel_id,
                "word_count": entity.word_count,
                "overall_score": _clamp_score(report.get("overall_score")),
                "verdict": str(report.get("verdict") or "体检完成"),
                "status": str(report.get("status") or "completed"),
                "completed_chapters": int(progress.get("completed_chapters") or 0),
                "total_chapters": int(progress.get("total_chapters") or 0),
                "created_at": entity.created_at,
            })
        return summaries

    async def get_report(self, report_id: int, owner_id: int) -> dict:
        entity = await self.report_repo.get_by_owner(report_id, owner_id)
        if not entity:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="体检报告不存在")
        return self._read(entity)

    async def delete_report(self, report_id: int, owner_id: int) -> None:
        entity = await self.report_repo.get_by_owner(report_id, owner_id)
        if not entity:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="体检报告不存在")
        await self.report_repo.delete(entity)
        await self.db.commit()
