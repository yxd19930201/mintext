import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.novel_generate import GenerateNovelOutlineRequest
from app.schemas.generation_mode import GenerationModeOptions
from app.services.generation_mode_service import resolve_generation_config
from app.services.novel_generate_service import NovelGenerateService


def test_novel_outline_free_mode_uses_browser_provider_not_default_api():
    db = AsyncMock()
    service = NovelGenerateService(db)
    novel = SimpleNamespace(
        id=9,
        title="凡人修仙",
        genre="仙侠",
        synopsis="少年获得机缘后踏上修行之路。",
        ai_config_id=77,
        system_prompt=None,
        outline=None,
        story_roadmap=json.dumps(
            {
                "total_chapters": 5,
                "protagonist": {"name": "陈凡", "identity": "少年", "initial_state": {}},
                "stages": [{"id": "S1", "start_chapter": 1, "end_chapter": 5}],
            },
            ensure_ascii=False,
        ),
        state_ledger=json.dumps({"current_chapter": 0, "protagonist": {"name": "陈凡"}}, ensure_ascii=False),
        canon_facts="[]",
        continuity_audits="[]",
    )
    service.novel_repo.get_by_id_and_owner = AsyncMock(return_value=novel)
    service.novel_repo.update = AsyncMock(return_value=novel)
    service.ai_config_repo.get = AsyncMock()
    service.ai_config_repo.get_default = AsyncMock()

    outline = {
        "total_chapters": 5,
        "theme": "凡人成长",
        "chapters": [
            {"chapter_number": 1, "title": "机缘", "synopsis": "陈凡获得修行机缘。"}
        ],
    }
    request = GenerateNovelOutlineRequest(
        novel_id=9,
        total_chapters=5,
        start_chapter=1,
        end_chapter=1,
        economy_mode=True,
        free_mode=True,
        free_provider="deepseek",
    )

    with patch(
        "app.services.novel_generate_service.ai_service.generate_novel_outline",
        new=AsyncMock(return_value=json.dumps(outline, ensure_ascii=False)),
    ) as generate:
        result = asyncio.run(service.generate_outline(request, owner_id=1))

    config = generate.await_args.kwargs["ai_config"]
    assert config.model == "deepseek"
    assert config.api_key == "web-login"
    assert config.base_url.endswith("/v1")
    assert result.chapters[0].title == "机缘"
    service.ai_config_repo.get.assert_not_awaited()
    service.ai_config_repo.get_default.assert_not_awaited()


def test_explicit_generation_modes_normalize_legacy_flags():
    economy = GenerationModeOptions(generation_mode="economy")
    standard = GenerationModeOptions(generation_mode="strict")
    free = GenerationModeOptions(generation_mode="free", free_provider="chatgpt")

    assert economy.economy_mode is True and economy.free_mode is False
    assert standard.economy_mode is False and standard.free_mode is False
    assert free.economy_mode is True and free.free_mode is True


def test_central_resolver_free_mode_never_reads_api_repository():
    repo = SimpleNamespace(get=AsyncMock(), get_default=AsyncMock())
    config = asyncio.run(
        resolve_generation_config(
            repo,
            GenerationModeOptions(generation_mode="free", free_provider="deepseek"),
            explicit_config_id=999,
            entity_config_id=888,
        )
    )

    assert config.model == "deepseek"
    assert config.api_key == "web-login"
    repo.get.assert_not_awaited()
    repo.get_default.assert_not_awaited()
