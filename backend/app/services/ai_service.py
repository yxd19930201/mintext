"""
AI Service — real httpx implementation for OpenAI-compatible APIs.
Falls back to settings (env vars) when no explicit config is provided.
"""
from __future__ import annotations

import json
import re
import httpx
from fastapi import HTTPException, status
from app.config import settings
from app.models.ai_config import AIConfig


class AIService:
    async def _call(
        self,
        messages: list[dict],
        base_url: str,
        api_key: str,
        model: str,
        json_mode: bool = False,
    ) -> str:
        url = base_url.rstrip("/") + "/chat/completions"
        payload = {"model": model, "messages": messages}
        if json_mode and ("gpt" in model or "deepseek" in model):
            payload["response_format"] = {"type": "json_object"}
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI API error: {e.response.text}")
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"AI call failed: {str(e)}")

    def _resolve(self, ai_config: AIConfig | None) -> tuple[str, str, str]:
        """Return (base_url, api_key, model) from config or settings fallback."""
        if ai_config:
            return ai_config.base_url, ai_config.api_key, ai_config.model
        return settings.AI_BASE_URL, settings.AI_API_KEY, settings.AI_MODEL

    async def generate_outline(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_episodes: int,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate outline JSON string."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = system_prompt or (
            "你是一位专业的短剧编剧，擅长创作引人入胜的短剧剧本大纲。"
            "请严格按照用户要求的 JSON 格式输出，不要添加任何额外说明。"
        )
        user_msg = (
            f"请为以下短剧创作分集大纲，共 {total_episodes} 集。\n"
            f"剧名：{title}\n"
            f"类型：{genre or '不限'}\n"
            f"故事梗概：{synopsis}\n\n"
            "请以纯 JSON 格式返回，格式如下（不要有任何其他文字）：\n"
            '{"total_episodes": N, "theme": "核心主题", "episodes": ['
            '{"episode_number": 1, "title": "集标题", "synopsis": "本集简介"}, ...]}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        parsed = self._parse_json_response(raw, "outline")
        return json.dumps(parsed, ensure_ascii=False)

    async def generate_script(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate script content."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = system_prompt or (
            "你是一位专业的短剧编剧，擅长创作对话生动、节奏紧凑的短剧剧本。"
            "请按照标准剧本格式输出，包含场景描述、人物对话和动作指示。"
        )
        user_content = ""
        if context:
            user_content += f"项目背景：\n{context}\n\n"
        user_content += f"请根据以下要求生成本集剧本：\n{prompt}"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_content}]
        return await self._call(messages, base_url, api_key, model)

    async def improve_script(
        self,
        content: str,
        instruction: str,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Improve existing script content."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = "你是一位专业的短剧编剧，请根据用户的优化指令改进剧本内容。"
        user_msg = f"原剧本：\n{content}\n\n优化指令：{instruction}\n\n请输出优化后的完整剧本。"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        return await self._call(messages, base_url, api_key, model)

    def _parse_json_response(self, raw: str, context: str) -> dict:
        """Parse JSON from AI response, stripping markdown fences if needed."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI returned invalid JSON for {context}. Raw response: {raw[:300]}"
        )

    async def _generate_chapters_range(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_chapters: int,
        start: int,
        end: int,
        theme: str,
        sys_msg: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> tuple[list[dict], str]:
        """Generate chapters [start, end] as a single AI call. Returns list of chapter dicts."""
        theme_hint = f"\n核心主题（请保持一致）：{theme}" if theme else ""
        count = end - start + 1
        user_msg = (
            f"请为以下小说创作第 {start}~{end} 章的章节大纲（共 {total_chapters} 章，本次只生成这 {count} 章）。\n"
            f"小说名：{title}\n"
            f"类型：{genre or '不限'}\n"
            f"故事大概：{synopsis}{theme_hint}\n\n"
            f"严格只输出第 {start} 到第 {end} 章，纯 JSON，不要任何其他文字：\n"
            '{"total_chapters": ' + str(total_chapters) + ', "theme": "核心主题", "chapters": ['
            '{"chapter_number": ' + str(start) + ', "title": "章节标题", "synopsis": "本章简介"}'
            + (', ...' if count > 1 else '') + ']}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        parsed = self._parse_json_response(raw, f"chapters {start}-{end}")
        return parsed.get("chapters", []), parsed.get("theme", theme)

    async def generate_novel_outline(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_chapters: int,
        start_chapter: int = 1,
        end_chapter: int | None = None,
        theme: str = "",
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate novel chapter outline for [start_chapter, end_chapter].
        On JSON parse failure, automatically falls back to chapter-by-chapter generation."""
        base_url, api_key, model = self._resolve(ai_config)
        end = end_chapter or total_chapters
        sys_msg = system_prompt or (
            "你是一位专业的网络小说作家，擅长创作引人入胜的长篇小说大纲。"
            "请严格按照用户要求的 JSON 格式输出，不要添加任何额外说明。"
        )

        all_chapters: list[dict] = []
        current_theme = theme

        # Try the whole range first; on failure fall back to one-by-one
        try:
            chapters, current_theme = await self._generate_chapters_range(
                title, genre, synopsis, total_chapters,
                start_chapter, end, current_theme, sys_msg, base_url, api_key, model,
            )
            all_chapters = chapters
        except HTTPException:
            # Fallback: generate one chapter at a time
            for ch_num in range(start_chapter, end + 1):
                for attempt in range(3):
                    try:
                        chapters, fetched_theme = await self._generate_chapters_range(
                            title, genre, synopsis, total_chapters,
                            ch_num, ch_num, current_theme, sys_msg, base_url, api_key, model,
                        )
                        if chapters:
                            all_chapters.extend(chapters)
                            if not current_theme and fetched_theme:
                                current_theme = fetched_theme
                        break
                    except HTTPException:
                        if attempt == 2:
                            # Give up on this chapter, insert placeholder
                            all_chapters.append({
                                "chapter_number": ch_num,
                                "title": f"第{ch_num}章",
                                "synopsis": "（生成失败，请手动补充）",
                            })

        result = {
            "total_chapters": total_chapters,
            "theme": current_theme,
            "chapters": all_chapters,
        }
        return json.dumps(result, ensure_ascii=False)

    async def generate_chapter(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate chapter content (approximately 4000 words)."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = system_prompt or (
            "你是一位专业的网络小说作家，擅长创作情节紧凑、文笔流畅的小说章节。"
            "严格按照用户指定的字数范围写作，在字数范围内完整交代本章剧情，自然收尾，不要强行拖长。"
        )
        user_content = ""
        if context:
            user_content += f"小说背景：\n{context}\n\n"
        user_content += f"请根据以下要求生成本章内容：\n{prompt}"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_content}]
        return await self._call(messages, base_url, api_key, model)

    async def update_knowledge_graph(
        self,
        chapter_content: str,
        chapter_number: int,
        chapter_title: str,
        existing_graph: str = "",
        ai_config: AIConfig | None = None,
    ) -> str:
        """Extract characters and events from chapter content, merge into existing graph."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = (
            "你是一位专业的小说分析师，擅长从章节内容中提取人物关系。"
            "请严格按照 JSON 格式输出，不要添加任何额外说明。"
        )
        existing_hint = f"\n\n已有图谱（必须完整保留所有已有人物，在此基础上新增本章内容）：\n{existing_graph[:2000]}" if existing_graph else ""
        user_msg = (
            f"请从以下第 {chapter_number} 章《{chapter_title}》的内容中，提取并更新人物关系。{existing_hint}\n\n"
            f"章节内容：\n{chapter_content[:1500]}\n\n"
            "提取规则：\n"
            "1. 只记录与主角有直接互动或关系的人物（主角本人必须包含），忽略与主角无关的次要人物。\n"
            "2. 删除只在一章中出现过一次、且对主角影响不重要的人物。\n"
            "3. 已有图谱中多次出现的人物必须保留并更新描述，不得删除。\n"
            "4. description 字段限制在30字以内，只写核心身份特征，不要罗列每章情节。\n\n"
            "请以纯 JSON 格式返回完整图谱：\n"
            '{"characters": [{"name": "人物名", "role": "身份/角色", "description": "简要描述(30字内)", '
            '"relations": [{"target": "关联人物名", "relation": "关系描述"}]}]}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        parsed = self._parse_json_response(raw, "knowledge graph")
        return json.dumps(parsed, ensure_ascii=False)


ai_service = AIService()
