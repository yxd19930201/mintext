from __future__ import annotations

import json
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_repo import ProjectRepository
from app.repositories.episode_repo import EpisodeRepository
from app.repositories.script_repo import ScriptRepository
from app.repositories.ai_config_repo import AIConfigRepository
from app.schemas.ai_generate import GenerateOutlineRequest, GenerateScriptRequest, BatchGenerateRequest, GenerateNextEpisodeRequest, OutlineResult
from app.services.ai_service import ai_service


class AIGenerateService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.project_repo = ProjectRepository(db)
        self.episode_repo = EpisodeRepository(db)
        self.script_repo = ScriptRepository(db)
        self.ai_config_repo = AIConfigRepository(db)

    async def _get_ai_config(self, config_id: int | None):
        if config_id:
            cfg = await self.ai_config_repo.get(config_id)
            if not cfg:
                raise HTTPException(status_code=404, detail="AI config not found")
            return cfg
        return await self.ai_config_repo.get_default()

    async def generate_outline(self, req: GenerateOutlineRequest, owner_id: int) -> OutlineResult:
        project = await self.project_repo.get(req.project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not project.synopsis:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Project has no synopsis")

        config_id = req.ai_config_id or project.ai_config_id
        ai_config = await self._get_ai_config(config_id)
        system_prompt = req.system_prompt or project.system_prompt

        outline_json = await ai_service.generate_outline(
            title=project.title,
            genre=project.genre,
            synopsis=project.synopsis,
            total_episodes=req.total_episodes,
            system_prompt=system_prompt,
            ai_config=ai_config,
        )

        try:
            outline_data = json.loads(outline_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to parse outline JSON")

        await self.project_repo.update(project, outline=outline_json, total_episodes=req.total_episodes)
        return OutlineResult(**outline_data)

    async def generate_script_for_episode(
        self, episode_id: int, req: GenerateScriptRequest, owner_id: int
    ) -> dict:
        episode = await self.episode_repo.get(episode_id)
        if not episode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Episode not found")

        project = await self.project_repo.get(episode.project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        config_id = req.ai_config_id or project.ai_config_id
        ai_config = await self._get_ai_config(config_id)
        system_prompt = req.system_prompt or project.system_prompt

        context_parts = []
        if project.synopsis:
            context_parts.append(f"剧名：{project.title}\n故事梗概：{project.synopsis}")

        # 拼入上一集剧本结尾，保证情节衔接
        if episode.episode_number > 1:
            prev_episodes = await self.episode_repo.list(project_id=episode.project_id)
            prev_ep = next((e for e in prev_episodes if e.episode_number == episode.episode_number - 1), None)
            if prev_ep:
                prev_scripts = await self.script_repo.list(episode_id=prev_ep.id)
                if prev_scripts and prev_scripts[0].content:
                    prev_content = prev_scripts[0].content
                    # 只取最后 500 字避免 token 过多
                    snippet = prev_content[-500:] if len(prev_content) > 500 else prev_content
                    context_parts.append(
                        f"上一集（第 {prev_ep.episode_number} 集：{prev_ep.title}）结尾内容：\n{snippet}\n"
                        f"请确保本集剧情与上一集自然衔接。"
                    )

        if req.extra_context:
            context_parts.append(req.extra_context)
        context = "\n\n".join(context_parts) if context_parts else None

        prompt = f"第 {episode.episode_number} 集：{episode.title}"
        if episode.synopsis:
            prompt += f"\n本集简介：{episode.synopsis}"

        content = await ai_service.generate_script(
            prompt=prompt,
            context=context,
            system_prompt=system_prompt,
            ai_config=ai_config,
        )

        # Upsert script record
        scripts = await self.script_repo.list(episode_id=episode_id)
        if scripts:
            script = await self.script_repo.update(scripts[0], content=content, status="generated")
        else:
            script = await self.script_repo.create(episode_id=episode_id, content=content, status="generated")

        return {"episode_id": episode_id, "script_id": script.id, "content": content}

    async def batch_generate(self, req: BatchGenerateRequest, owner_id: int) -> dict:
        project = await self.project_repo.get(req.project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        episodes = await self.episode_repo.list(project_id=req.project_id)
        # 按集号排序，保证衔接上下文按顺序生成
        episodes.sort(key=lambda e: e.episode_number)

        if req.only_missing:
            # 过滤掉已有剧本的集
            filtered = []
            for ep in episodes:
                scripts = await self.script_repo.list(episode_id=ep.id)
                if not scripts or not scripts[0].content:
                    filtered.append(ep)
            episodes = filtered

        total = len(episodes)
        succeeded = 0
        failed = 0
        errors: list[dict] = []

        script_req = GenerateScriptRequest(
            ai_config_id=req.ai_config_id,
            system_prompt=req.system_prompt,
        )

        for ep in episodes:
            try:
                await self.generate_script_for_episode(ep.id, script_req, owner_id)
                succeeded += 1
            except Exception as e:
                failed += 1
                errors.append({"episode_id": ep.id, "error": str(e)})

        return {"total": total, "succeeded": succeeded, "failed": failed, "errors": errors}

    async def generate_next_episode(self, req: GenerateNextEpisodeRequest, owner_id: int) -> dict:
        """根据最后一集剧本内容，生成下一集分集信息和剧本。"""
        project = await self.project_repo.get(req.project_id)
        if not project or project.owner_id != owner_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        config_id = req.ai_config_id or project.ai_config_id
        ai_config = await self._get_ai_config(config_id)
        system_prompt = req.system_prompt or project.system_prompt

        # 找到当前最后一集
        episodes = await self.episode_repo.list(project_id=req.project_id)
        episodes.sort(key=lambda e: e.episode_number)
        next_number = (episodes[-1].episode_number + 1) if episodes else 1
        last_ep = episodes[-1] if episodes else None

        # 构建上下文
        context_parts = []
        if project.synopsis:
            context_parts.append(f"剧名：{project.title}\n故事梗概：{project.synopsis}")

        if last_ep:
            context_parts.append(f"已有 {len(episodes)} 集，当前最新一集为第 {last_ep.episode_number} 集：{last_ep.title}")
            last_scripts = await self.script_repo.list(episode_id=last_ep.id)
            if last_scripts and last_scripts[0].content:
                snippet = last_scripts[0].content[-800:] if len(last_scripts[0].content) > 800 else last_scripts[0].content
                context_parts.append(f"上一集结尾内容：\n{snippet}")

        context = "\n\n".join(context_parts) if context_parts else None

        # 第一步：让 AI 生成下一集的标题和简介
        from app.services.ai_service import AIService
        svc = AIService()
        title_prompt = (
            f"请为第 {next_number} 集生成标题和简介，要求与前集情节自然衔接，推进故事发展。\n"
            f"以 JSON 格式返回：{{\"title\": \"集标题\", \"synopsis\": \"本集简介（100字以内）\"}}"
        )
        title_messages = [
            {"role": "system", "content": system_prompt or "你是一位专业的短剧编剧，只输出纯JSON，不加任何说明。"},
            {"role": "user", "content": (context or "") + "\n\n" + title_prompt},
        ]
        base_url, api_key, model = svc._resolve(ai_config)
        raw = await svc._call(title_messages, base_url, api_key, model, json_mode=True)

        import re
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()
        try:
            meta = json.loads(cleaned)
            ep_title = meta.get("title", f"第{next_number}集")
            ep_synopsis = meta.get("synopsis", "")
        except Exception:
            ep_title = f"第{next_number}集"
            ep_synopsis = ""

        # 创建新分集
        new_ep = await self.episode_repo.create(
            project_id=req.project_id,
            title=ep_title,
            episode_number=next_number,
            synopsis=ep_synopsis,
        )

        # 第二步：生成剧本
        script_req = GenerateScriptRequest(ai_config_id=req.ai_config_id, system_prompt=req.system_prompt)
        result = await self.generate_script_for_episode(new_ep.id, script_req, owner_id)

        return {
            "episode_id": new_ep.id,
            "episode_number": next_number,
            "title": ep_title,
            "synopsis": ep_synopsis,
            "script_id": result["script_id"],
        }
