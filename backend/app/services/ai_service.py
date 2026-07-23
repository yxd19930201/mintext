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
from app.services.creative_prompt_service import creative_prompt, normalize_short_script
from app.services.novel_skill_service import novel_skill_prompt


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
            if not ai_config.base_url or not ai_config.model:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="AI_CONFIG_REQUIRED:AI 模型配置不完整，请进入“设置 → AI 模型配置”补充接口地址和模型名。",
                )
            return ai_config.base_url, ai_config.api_key, ai_config.model
        if not settings.AI_API_KEY:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="AI_CONFIG_REQUIRED:此功能需要使用 AI 模型。请先进入“设置 → AI 模型配置”，添加接口地址、API Key 和模型名，并设为默认配置。",
            )
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
        sys_msg = creative_prompt("short_outline", system_prompt)
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
        sys_msg = creative_prompt("short_script", system_prompt)
        user_content = ""
        if context:
            user_content += f"项目背景：\n{context}\n\n"
        user_content += f"请根据以下要求生成本集剧本：\n{prompt}"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_content}]
        raw = await self._call(messages, base_url, api_key, model)
        return normalize_short_script(raw)

    async def improve_script(
        self,
        content: str,
        instruction: str,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Improve existing script content."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = creative_prompt("script_improve")
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
        sys_msg = novel_skill_prompt("outline", system_prompt)

        all_chapters: list[dict] = []
        current_theme = theme

        # Try the whole range first; on failure fall back to one-by-one
        try:
            chapters, current_theme = await self._generate_chapters_range(
                title, genre, synopsis, total_chapters,
                start_chapter, end, current_theme, sys_msg, base_url, api_key, model,
            )
            all_chapters = chapters
        except HTTPException as exc:
            # Only retry malformed model output. Authentication, networking and
            # configuration errors must reach the UI instead of becoming fake
            # "生成失败" outline placeholders.
            if not str(exc.detail).startswith("AI returned invalid JSON"):
                raise
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
                    except HTTPException as exc:
                        if not str(exc.detail).startswith("AI returned invalid JSON"):
                            raise
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
        sys_msg = novel_skill_prompt("draft", system_prompt)
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
        sys_msg = novel_skill_prompt("memory")
        existing_hint = f"\n\n已有连续性记忆（保留所有仍有效事实，在此基础上更新）：\n{existing_graph[:5000]}" if existing_graph else ""
        if len(chapter_content) <= 6000:
            chapter_excerpt = chapter_content
        else:
            chapter_excerpt = chapter_content[:3000] + "\n\n【中段省略】\n\n" + chapter_content[-3000:]
        user_msg = (
            f"请从以下第 {chapter_number} 章《{chapter_title}》的内容中，提取并更新人物关系。{existing_hint}\n\n"
            f"章节内容：\n{chapter_excerpt}\n\n"
            "提取规则：\n"
            "1. 只记录与主角有直接互动或关系的人物（主角本人必须包含），忽略与主角无关的次要人物。\n"
            "2. 删除只在一章中出现过一次、且对主角影响不重要的人物。\n"
            "3. 已有图谱中多次出现的人物必须保留并更新描述，不得删除。\n"
            "4. description 字段限制在30字以内，只写核心身份特征，不要罗列每章情节。\n"
            "5. events 记录本章造成的不可逆变化；open_threads 记录仍待兑现的危险、承诺、伏笔或期限。\n"
            "6. continuity 保存下一章不可违背的时间地点、伤势、资源物件、知识状态和承诺。\n\n"
            "请以纯 JSON 格式返回完整连续性记忆：\n"
            '{"characters": [{"name": "人物名", "role": "身份/角色", "description": "简要描述(30字内)", '
            '"relations": [{"target": "关联人物名", "relation": "关系描述"}]}], '
            '"events": [{"chapter": 1, "title": "事件名", "description": "不可逆变化"}], '
            '"open_threads": [{"thread": "未决线索", "last_chapter": 1, "status": "open"}], '
            '"continuity": {"time_place": "当前时空", "injuries": [], "items": [], "knowledge": [], "promises": []}}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        parsed = self._parse_json_response(raw, "knowledge graph")
        return json.dumps(parsed, ensure_ascii=False)


ai_service = AIService()
