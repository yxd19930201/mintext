"""Runtime adapter for the bundled novel-continuity-writer skill.

The original skill contains the full workflow and reference material.  This
module keeps API prompts small by injecting only the rules needed at each AI
generation phase.
"""
from __future__ import annotations


_BASE_RULES = """你正在遵循 novel-continuity-writer 长篇小说连续性创作规范。
- 把故事当作持续运行的内容产品；聊天内容不能覆盖已提供的小说正史、设定和连续性记忆。
- 大故事提供长期目标，小故事提供即时追读；每章至少推进冲突、信息、资源、关系、名声或威胁之一。
- 主角必须主动选择；阻力方必须有资源、位置或合理判断，不能靠降智送机会。
- 压力、选择、反馈、收益与新代价要形成因果链；章末必须留下危险、选择、期限、收益或揭露。
- 人物有独立欲望与不同口吻；用现场动作和反馈替代解释腔、总结腔与模板化枚举。
- 不得改变上下文中的姓名、身份、伤势、物件归属、知识差、时间顺序、承诺和已发生事件。
"""

_PHASE_RULES = {
    "outline": """当前任务是规划章节。
- 每3至5章形成一个可局部结算的小故事，同时服务全书主线。
- 每章简介必须明确写出：冲突、推进、即时满足/反馈、章尾钩子，以及产生的不可逆变化。
- 相邻章节的因果、时间、人物目标和伏笔必须连续；避免连续重复同类爽点或互动。
- 只输出调用方要求的 JSON，不要附加说明。""",
    "draft": """当前任务是撰写章节正文。
- 严格兑现本章标题和简介，不越写到后续章节，也不提前回收未安排的长线伏笔。
- 从明确压力进入场景，让人物通过动作、对白和选择推动冲突；至少出现一次反馈或局部结算。
- 结尾令信息、资源、关系、风险或位置发生变化，并自然制造下一章追读动力。
- 删除可移除而不影响主线、人物或信息的水段；避免“他知道/他意识到”、抽象震惊和作者总结。
- 输出只有小说正文，不写分析、提纲、创作说明或 Markdown 围栏。""",
    "next": """当前任务是设计紧接正史的下一章。
- 从上一章尚未解决的压力、收益或代价中选择最强发动机。
- 简介必须给出具体诱因、阻力、主角选择、局部结算和新钩子，并保持人物知识与物件持有链连续。
- 只输出调用方要求的 JSON，不要附加说明。""",
    "memory": """当前任务是更新正史连续性记忆。
- 完整保留仍有效的既有事实，只根据本章正文追加或更新；不得把推测写成事实。
- 记录人物状态/关系、关键事件、未回收线索，以及时间地点、资源物件、伤势、知识状态和承诺的变化。
- 关系描述要短，但关键事件和未决线索必须足以驱动后续章节。
- 只输出调用方要求的 JSON，不要附加说明。""",
}


def novel_skill_prompt(phase: str, custom_prompt: str | None = None) -> str:
    """Compose the mandatory skill prompt with an optional user prompt."""
    phase_rules = _PHASE_RULES.get(phase)
    if phase_rules is None:
        raise ValueError(f"Unknown novel skill phase: {phase}")
    parts = [_BASE_RULES.strip(), phase_rules.strip()]
    if custom_prompt and custom_prompt.strip():
        parts.append("项目自定义文风与要求（不得违反以上连续性规则）：\n" + custom_prompt.strip())
    return "\n\n".join(parts)
