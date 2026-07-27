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

        candidates = [cleaned]
        first_brace = cleaned.find("{")
        last_brace = cleaned.rfind("}")
        if first_brace >= 0 and last_brace > first_brace:
            candidates.append(cleaned[first_brace:last_brace + 1])

        for candidate in candidates:
            # Models occasionally leave trailing commas even in JSON mode.
            variants = [
                candidate,
                re.sub(r",\s*([}\]])", r"\1", candidate),
            ]
            for variant in variants:
                try:
                    parsed = json.loads(variant)
                    if isinstance(parsed, dict):
                        return parsed
                except json.JSONDecodeError:
                    continue
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI returned invalid JSON for {context}. Raw response: {raw[:300]}"
        )

    async def generate_story_roadmap(
        self,
        title: str,
        genre: str | None,
        synopsis: str,
        total_chapters: int,
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Create the fixed whole-book stage contract used by every later call."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("roadmap")
        user = (
            f"小说名：{title}\n类型：{genre or '不限'}\n总章节数：{total_chapters}\n"
            f"故事梗概：{synopsis}\n\n"
            "请输出纯 JSON：\n"
            '{"total_chapters": 50, "protagonist": {"name": "主角名", "identity": "初始身份", '
            '"initial_state": {"wealth": "初始财富", "assets": [], "career": "初始职业", '
            '"abilities": [], "relationships": []}}, "stages": ['
            '{"id": "S1", "name": "阶段名", "start_chapter": 1, "end_chapter": 10, '
            '"goal": "阶段目标", "entry_condition": "进入条件", "exit_condition": "完成标志", '
            '"required_plot_points": ["必须发生的情节"], "state_gain": "不可逆获得或失去", '
            '"transition_to_next": "自然进入下一阶段的因果事件"}]}'
        )
        last_error = "roadmap missing"
        for _ in range(3):
            raw = await self._call(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                base_url, api_key, model, json_mode=True,
            )
            roadmap = self._parse_json_response(raw, "story roadmap")
            stages = sorted(
                roadmap.get("stages") or [],
                key=lambda item: item.get("start_chapter", 0),
            )
            expected_start = 1
            valid = bool(stages)
            for stage in stages:
                start = stage.get("start_chapter")
                end = stage.get("end_chapter")
                if (
                    start != expected_start
                    or not isinstance(end, int)
                    or end < start
                    or not stage.get("entry_condition")
                    or not stage.get("exit_condition")
                ):
                    valid = False
                    break
                expected_start = end + 1
            if valid and expected_start == total_chapters + 1:
                roadmap["total_chapters"] = total_chapters
                roadmap["stages"] = stages
                return roadmap
            last_error = (
                "stage ranges must be continuous from chapter 1 through "
                f"chapter {total_chapters}, with entry and exit conditions"
            )
            user += f"\n\n上一次路线图无效：{last_error}。请完整重做。"
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI failed to create a valid story roadmap: {last_error}",
        )

    async def audit_outline_candidate(
        self,
        synopsis: str,
        roadmap: dict,
        state_ledger: dict,
        canon_facts: list,
        previous_chapters: list[dict],
        candidate_chapters: list[dict],
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Audit an outline batch and return approved or a complete replacement."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("audit_outline")
        payload = {
            "synopsis": synopsis,
            "roadmap": roadmap,
            "state_ledger": state_ledger,
            "canon_facts": canon_facts,
            "previous_chapters": previous_chapters[-10:],
            "candidate_chapters": candidate_chapters,
        }
        user = (
            f"审核材料：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "输出纯 JSON："
            '{"approved": true, "issues": [], "revised_chapters": ['
            '{"chapter_number": 1, "title": "标题", "synopsis": "完整简介", '
            '"stage_id": "S1", "before_state": {}, "after_state": {}, '
            '"irreversible_facts": [], "transition": "与前后阶段的因果承接"}]}。'
            "若不通过，revised_chapters 必须包含本批全部章节的完整替换稿；"
            "若通过，也原样返回完整 candidate_chapters。"
        )
        last_error: HTTPException | None = None
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(1, 3):
            raw = await self._call(messages, base_url, api_key, model, json_mode=True)
            try:
                return self._parse_json_response(raw, "outline continuity audit")
            except HTTPException as exc:
                last_error = exc
                messages = [
                    {"role": "system", "content": system},
                    {
                        "role": "user",
                        "content": (
                            user
                            + "\n\nThe previous response was not valid JSON. "
                            "Return exactly one JSON object without markdown, comments, or trailing commas."
                        ),
                    },
                ]
        raise last_error or HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI returned an invalid outline audit response.",
        )

    async def audit_chapter_candidate(
        self,
        chapter_number: int,
        chapter_outline: dict,
        content: str,
        roadmap: dict,
        state_ledger: dict,
        canon_facts: list,
        previous_ending: str,
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Return a strict pass/fail review. A failed draft is never persisted."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("audit_draft")
        payload = {
            "chapter_number": chapter_number,
            "chapter_outline": chapter_outline,
            "roadmap": roadmap,
            "state_ledger": state_ledger,
            "canon_facts": canon_facts[-100:],
            "previous_ending": previous_ending,
            "candidate_content": content,
        }
        user = (
            f"审核材料：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            '只输出 JSON：{"approved": true, "issues": [], '
            '"summary": "审核结论与本章状态变化摘要"}。'
            "issues 每项必须包含 type、evidence、conflict_with、repair_instruction。"
        )
        raw = await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url, api_key, model, json_mode=True,
        )
        return self._parse_json_response(raw, "chapter continuity audit")

    async def revise_chapter_candidate(
        self,
        original_content: str,
        issues: list,
        context: str,
        prompt: str,
        ai_config: AIConfig | None = None,
    ) -> str:
        """Repair only the rejected draft; the result must be audited again."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("draft")
        user = (
            f"正史背景与硬约束：\n{context}\n\n"
            f"本章任务：\n{prompt}\n\n"
            f"未通过审核的问题：\n{json.dumps(issues, ensure_ascii=False)}\n\n"
            f"待返修正文：\n{original_content}\n\n"
            "请按每条 repair_instruction 完整重写本章。不得用一句解释掩盖冲突；"
            "必须在情节中建立充分因果。只输出修订后的小说正文。"
        )
        return await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url, api_key, model,
        )

    async def extract_canon_update(
        self,
        chapter_number: int,
        chapter_title: str,
        content: str,
        existing_ledger: dict,
        existing_facts: list,
        ai_config: AIConfig | None = None,
    ) -> dict:
        """Build the full post-chapter ledger only after the draft passed review."""
        base_url, api_key, model = self._resolve(ai_config)
        system = novel_skill_prompt("canon")
        payload = {
            "chapter_number": chapter_number,
            "chapter_title": chapter_title,
            "existing_state_ledger": existing_ledger,
            "existing_irreversible_facts": existing_facts[-100:],
            "approved_content": content,
        }
        user = (
            f"正史更新材料：\n{json.dumps(payload, ensure_ascii=False)}\n\n"
            "输出纯 JSON："
            '{"state_ledger": {"current_chapter": 1, "time_place": "", '
            '"protagonist": {"name": "", "identity": "", "career": "", "wealth": "", '
            '"cash": "", "assets": [], "debts": [], "abilities": [], "reputation": "", '
            '"injuries": [], "relationships": [], "knowledge": [], "items": [], '
            '"promises": [], "open_conflicts": []}, "supporting_characters": []}, '
            '"new_irreversible_facts": [{"chapter": 1, "type": "wealth|identity|asset|ability|'
            'relationship|time|event", "fact": "不可逆事实", "cause": "正文依据"}]}'
        )
        raw = await self._call(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            base_url, api_key, model, json_mode=True,
        )
        return self._parse_json_response(raw, "canon ledger update")

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
        previous_chapters: list[dict] | None = None,
    ) -> tuple[list[dict], str]:
        """Generate chapters [start, end] as a single AI call. Returns list of chapter dicts."""
        theme_hint = f"\n核心主题（请保持一致）：{theme}" if theme else ""
        previous_chapters = previous_chapters or []
        start_progress = round((start - 1) / total_chapters * 100)
        end_progress = round(end / total_chapters * 100)
        remaining_chapters = max(total_chapters - end, 0)
        progress_hint = (
            "\n\n【全书进度坐标与剧情推进（与连续性同等重要）】\n"
            f"本批次位于全书约 {start_progress}%～{end_progress}% 的位置，"
            f"生成后还剩 {remaining_chapters} 章。\n"
            "必须先根据“故事梗概”识别其中按时间或因果排列的全部重要阶段、行业、目标和重大事件，"
            "再按总章数把它们合理分配到开篇、发展、中段、后段和结局。\n"
            "开篇1～5章只用于锁定主角身份、人物关系和世界观，不代表后续必须停留在开篇的剧情阶段；"
            "最近章节只用于保证因果承接，也不允许反复复制同一阶段、同一目标或同类事件。\n"
            "若梗概包含多个连续阶段（例如股票、楼市、互联网），必须让前一阶段产生明确成果或转折，"
            "并在合理章数内进入下一阶段，确保结局前覆盖全部阶段；不得因为强调连续性而长期原地打转。\n"
            "本批次既要承接上一章，又必须产生不可逆的新进展，并为梗概中的下一项尚未完成的重要阶段铺垫。\n"
        )
        anchor_chapters = previous_chapters[:5]
        recent_chapters = previous_chapters[-10:]
        continuity_chapters = {
            chapter["chapter_number"]: chapter
            for chapter in [*anchor_chapters, *recent_chapters]
            if chapter.get("chapter_number", 0) < start
        }
        continuity_hint = ""
        if continuity_chapters:
            continuity_json = json.dumps(
                list(continuity_chapters.values()),
                ensure_ascii=False,
            )
            continuity_hint = (
                "\n\n【已确定的正史大纲（不可改写）】\n"
                f"{continuity_json}\n"
                "必须延续上述主角、身份、核心目标、人物关系、时间线、资源状态、未解决冲突和上一章钩子。"
                "不得在本批次重新定义主角，不得另起一个无关故事，不得把新人物写成新的主角。"
                f"第 {start} 章必须直接承接第 {start - 1} 章的结果或钩子。"
            )
        count = end - start + 1
        user_msg = (
            f"请为以下小说创作第 {start}~{end} 章的章节大纲（共 {total_chapters} 章，本次只生成这 {count} 章）。\n"
            f"小说名：{title}\n"
            f"类型：{genre or '不限'}\n"
            f"故事大概：{synopsis}{theme_hint}{progress_hint}{continuity_hint}\n\n"
            "连续性硬性要求：全书默认只有同一位核心主角；除非原始故事大概明确指定群像或双主角，"
            "否则不得更换主角。新人物只能作为配角、对手或阶段人物，并必须由既有因果引入。"
            "每章的开端必须承接前章的结果，每章的变化必须进入下一章，禁止批次边界剧情重置。\n\n"
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
        previous_chapters: list[dict] | None = None,
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
                previous_chapters,
            )
            all_chapters = chapters
        except HTTPException as exc:
            # Only retry malformed model output. Authentication, networking and
            # configuration errors must reach the UI instead of becoming fake
            # "生成失败" outline placeholders.
            if not str(exc.detail).startswith("AI returned invalid JSON"):
                raise
            # Fallback: generate one chapter at a time
            continuity_chapters = list(previous_chapters or [])
            for ch_num in range(start_chapter, end + 1):
                for attempt in range(3):
                    try:
                        chapters, fetched_theme = await self._generate_chapters_range(
                            title, genre, synopsis, total_chapters,
                            ch_num, ch_num, current_theme, sys_msg, base_url, api_key, model,
                            continuity_chapters,
                        )
                        if chapters:
                            all_chapters.extend(chapters)
                            continuity_chapters.extend(chapters)
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
