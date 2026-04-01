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
        cleaned = raw.strip()
        # Strip markdown code fences if present
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()
        try:
            json.loads(cleaned)
            return cleaned
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                candidate = match.group(0)
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI returned invalid JSON for outline. Raw response: {raw[:300]}"
            )

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

    async def generate_novel_outline(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_chapters: int,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate novel chapter outline JSON string."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = system_prompt or (
            "你是一位专业的网络小说作家，擅长创作引人入胜的长篇小说大纲。"
            "请严格按照用户要求的 JSON 格式输出，不要添加任何额外说明。"
        )
        user_msg = (
            f"请为以下小说创作章节大纲，共 {total_chapters} 章。\n"
            f"小说名：{title}\n"
            f"类型：{genre or '不限'}\n"
            f"故事大概：{synopsis}\n\n"
            "请以纯 JSON 格式返回，格式如下（不要有任何其他文字）：\n"
            '{"total_chapters": N, "theme": "核心主题", "chapters": ['
            '{"chapter_number": 1, "title": "章节标题", "synopsis": "本章简介"}, ...]}'
        )
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await self._call(messages, base_url, api_key, model, json_mode=True)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()
        try:
            json.loads(cleaned)
            return cleaned
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                candidate = match.group(0)
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    pass
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"AI returned invalid JSON for novel outline. Raw response: {raw[:300]}"
            )

    async def generate_chapter(
        self,
        prompt: str,
        context: str | None = None,
        system_prompt: str | None = None,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Generate chapter content (approximately 3000 words)."""
        base_url, api_key, model = self._resolve(ai_config)
        sys_msg = system_prompt or (
            "你是一位专业的网络小说作家，擅长创作情节紧凑、文笔流畅的小说章节。"
            "每章内容约 3000 字，注重情节推进和人物刻画。"
        )
        user_content = ""
        if context:
            user_content += f"小说背景：\n{context}\n\n"
        user_content += f"请根据以下要求生成本章内容：\n{prompt}"
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_content}]
        return await self._call(messages, base_url, api_key, model)


ai_service = AIService()
