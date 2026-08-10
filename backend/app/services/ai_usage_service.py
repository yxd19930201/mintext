from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AIUsageService:
    """Persist aggregate AI token/cost usage without making another AI call."""

    def __init__(self) -> None:
        data_dir = Path(os.getenv("MINITEXT_DATA_DIR", "."))
        self.path = data_dir / "ai_usage.json"
        self._lock = threading.Lock()

    def _empty(self) -> dict[str, Any]:
        return {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_cny": 0.0,
            "calls": 0,
            "by_model": {},
            "updated_at": None,
        }

    def _read(self) -> dict[str, Any]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else self._empty()
        except (OSError, json.JSONDecodeError):
            return self._empty()

    def _write(self, value: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    def record(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        input_price_cny: float,
        output_price_cny: float,
    ) -> None:
        prompt_tokens = max(int(prompt_tokens or 0), 0)
        completion_tokens = max(int(completion_tokens or 0), 0)
        total_tokens = prompt_tokens + completion_tokens
        cost = (
            prompt_tokens / 1_000_000 * max(input_price_cny, 0)
            + completion_tokens / 1_000_000 * max(output_price_cny, 0)
        )
        with self._lock:
            stats = self._read()
            model_stats = stats.setdefault("by_model", {}).setdefault(
                model or "unknown",
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_cny": 0.0,
                    "calls": 0,
                },
            )
            for target in (stats, model_stats):
                target["prompt_tokens"] = int(target.get("prompt_tokens", 0)) + prompt_tokens
                target["completion_tokens"] = int(target.get("completion_tokens", 0)) + completion_tokens
                target["total_tokens"] = int(target.get("total_tokens", 0)) + total_tokens
                target["estimated_cost_cny"] = round(
                    float(target.get("estimated_cost_cny", 0)) + cost,
                    6,
                )
                target["calls"] = int(target.get("calls", 0)) + 1
            stats["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write(stats)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return self._read()

    def reset(self) -> dict[str, Any]:
        with self._lock:
            stats = self._empty()
            self._write(stats)
            return stats


ai_usage_service = AIUsageService()
