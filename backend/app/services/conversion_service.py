import json
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import HTTPException, status
from app.repositories.ai_config_repo import AIConfigRepository
from app.services.ai_service import ai_service
from app.schemas.conversion import (
    NovelToScriptRequest,
    ScriptToVideoRequest,
    NovelToScriptResult,
    ConversionEpisode,
    ScriptToVideoResult,
    VideoScriptScene,
)


class ConversionService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai_config_repo = AIConfigRepository(db)

    async def novel_to_script(self, req: NovelToScriptRequest, owner_id: int) -> NovelToScriptResult:
        """Convert novel text to short drama script"""
        # Get AI config
        ai_config = None
        if req.ai_config_id:
            ai_config = await self.ai_config_repo.get(req.ai_config_id)
            if not ai_config:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")

        # Build system prompt
        sys_msg = req.system_prompt or (
            "你是一位专业的短剧编剧，擅长将小说文本改编为紧凑、戏剧化的短剧剧本。"
            "请严格按照 JSON 格式输出，不要添加任何额外说明。"
        )

        # Build user prompt
        style_hint = f"风格要求：{req.style}\n" if req.style else ""
        user_msg = (
            f"请将以下小说文本改编为 {req.target_episodes} 集短剧剧本。\n"
            f"{style_hint}"
            f"要求：\n"
            f"1. 每集时长 3-5 分钟\n"
            f"2. 保留核心情节和冲突\n"
            f"3. 对话要简洁有力\n"
            f"4. 场景描述要具体\n\n"
            f"小说原文：\n{req.novel_text}\n\n"
            "请以纯 JSON 格式返回，格式如下（不要有任何其他文字）：\n"
            '{"total_episodes": N, "episodes": ['
            '{"episode_number": 1, "title": "集标题", "script": "剧本内容（包含场景、对话、动作）", "duration_estimate": "3-5分钟"}, ...]}'
        )

        # Call AI
        base_url, api_key, model = ai_service._resolve(ai_config)
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await ai_service._call(messages, base_url, api_key, model, json_mode=True)

        # Parse JSON
        import re
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                candidate = match.group(0)
                try:
                    data = json.loads(candidate)
                except json.JSONDecodeError:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"AI returned invalid JSON. Raw: {raw[:300]}"
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"AI returned invalid JSON. Raw: {raw[:300]}"
                )

        # Build result
        episodes = [
            ConversionEpisode(
                episode_number=ep["episode_number"],
                title=ep["title"],
                script=ep["script"],
                duration_estimate=ep.get("duration_estimate", "3-5分钟")
            )
            for ep in data.get("episodes", [])
        ]

        return NovelToScriptResult(
            total_episodes=data.get("total_episodes", len(episodes)),
            episodes=episodes,
        )

    async def script_to_video(self, req: ScriptToVideoRequest, owner_id: int) -> ScriptToVideoResult:
        """Convert script to Seedance 2.0 video generation format"""
        # Get AI config
        ai_config = None
        if req.ai_config_id:
            ai_config = await self.ai_config_repo.get(req.ai_config_id)
            if not ai_config:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="AI config not found")

        # Build system prompt
        sys_msg = req.system_prompt or (
            "你是一位专业的视频制作导演，擅长将剧本转换为视频生成模型（Seedance 2.0）所需的场景描述。"
            "请严格按照 JSON 格式输出，不要添加任何额外说明。"
        )

        # Build user prompt
        user_msg = (
            f"请将以下短剧剧本转换为 Seedance 2.0 视频生成模型所需的场景描述。\n\n"
            f"要求：\n"
            f"1. 每个场景包含：场景描述、时长、镜头角度、光线设置\n"
            f"2. 场景描述要具体、视觉化，适合 AI 视频生成\n"
            f"3. 镜头角度：特写/中景/全景/俯拍/仰拍等\n"
            f"4. 光线设置：自然光/柔光/逆光/暖色调/冷色调等\n"
            f"5. 每个场景时长建议 5-15 秒\n\n"
            f"剧本原文：\n{req.script_text}\n\n"
            "请以纯 JSON 格式返回，格式如下（不要有任何其他文字）：\n"
            '{"scenes": ['
            '{"scene_number": 1, "description": "场景的视觉描述", "duration": "10秒", '
            '"camera_angle": "中景", "lighting": "自然光"}, ...], '
            '"total_duration": "总时长"}'
        )

        # Call AI
        base_url, api_key, model = ai_service._resolve(ai_config)
        messages = [{"role": "system", "content": sys_msg}, {"role": "user", "content": user_msg}]
        raw = await ai_service._call(messages, base_url, api_key, model, json_mode=True)

        # Parse JSON
        import re
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if match:
                candidate = match.group(0)
                try:
                    data = json.loads(candidate)
                except json.JSONDecodeError:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"AI returned invalid JSON. Raw: {raw[:300]}"
                    )
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"AI returned invalid JSON. Raw: {raw[:300]}"
                )

        # Build result
        scenes = [
            VideoScriptScene(
                scene_number=sc["scene_number"],
                description=sc["description"],
                duration=sc.get("duration", "10秒"),
                camera_angle=sc.get("camera_angle", "中景"),
                lighting=sc.get("lighting", "自然光")
            )
            for sc in data.get("scenes", [])
        ]

        return ScriptToVideoResult(
            scenes=scenes,
            total_duration=data.get("total_duration", "未知"),
        )
