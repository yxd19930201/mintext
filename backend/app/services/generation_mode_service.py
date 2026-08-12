from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status

from app.services.ai_service import ai_service


def option_value(options: Any, name: str, default=None):
    if isinstance(options, dict):
        return options.get(name, default)
    return getattr(options, name, default)


def generation_mode(options: Any) -> str:
    explicit = option_value(options, "generation_mode")
    if explicit in {"economy", "strict", "free"}:
        return explicit
    if option_value(options, "free_mode", False):
        return "free"
    return "economy" if option_value(options, "economy_mode", False) else "strict"


async def resolve_generation_config(
    repo,
    options: Any,
    *,
    explicit_config_id: int | None = None,
    entity_config_id: int | None = None,
):
    """Resolve one immutable AI channel for an entire parent job."""
    if generation_mode(options) == "free":
        return ai_service.web_config(option_value(options, "free_provider", "deepseek"))

    config_id = explicit_config_id or entity_config_id
    if config_id:
        config = await repo.get(config_id)
        if not config:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="AI config not found",
            )
        return config
    return await repo.get_default()
