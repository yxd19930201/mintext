import asyncio
import json
from unittest.mock import AsyncMock

from app.services.ai_service import AIService


def test_later_outline_batch_includes_opening_and_recent_canon():
    service = AIService()
    service._call = AsyncMock(
        return_value=json.dumps(
            {
                "total_chapters": 20,
                "theme": "陈阳重生后改变命运",
                "chapters": [
                    {"chapter_number": 11, "title": "承接危机", "synopsis": "陈阳处理上一章危机"}
                ],
            },
            ensure_ascii=False,
        )
    )
    previous = [
        {"chapter_number": number, "title": f"第{number}章", "synopsis": f"陈阳推进主线{number}"}
        for number in range(1, 11)
    ]

    asyncio.run(
        service._generate_chapters_range(
            title="重生1992",
            genre="都市",
            synopsis="陈阳重生后创业",
            total_chapters=20,
            start=11,
            end=15,
            theme="陈阳改变命运",
            sys_msg="system",
            base_url="https://example.com",
            api_key="key",
            model="model",
            previous_chapters=previous,
        )
    )

    messages = service._call.await_args.args[0]
    prompt = messages[1]["content"]
    assert "已确定的正史大纲" in prompt
    assert "陈阳推进主线1" in prompt
    assert "陈阳推进主线10" in prompt
    assert "不得在本批次重新定义主角" in prompt
    assert "第 11 章必须直接承接第 10 章" in prompt
    assert "全书进度坐标与剧情推进" in prompt
    assert "本批次位于全书约 50%～75% 的位置" in prompt
    assert "开篇1～5章只用于锁定主角身份" in prompt
    assert "不得因为强调连续性而长期原地打转" in prompt
