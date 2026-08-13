"""UTF-8 end-to-end smoke driver for the local browser-AI workflow."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:4320/api/v1"


def call(method: str, path: str, payload: dict | None = None, timeout: int = 1500):
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {raw}") from exc
    return json.loads(raw) if raw else None


def setup() -> None:
    novel = call("POST", "/novels", {
        "title": "网页全链路测试·青灯谜案",
        "genre": "民国悬疑",
        "synopsis": "民国小镇中，年轻账房顾青发现旧当铺账本隐藏失踪案线索。他与女记者苏禾合作，在三天内追查真相，揭露掌柜伪造地契侵吞家产的阴谋。人物、时间和证据必须连续。",
        "total_chapters": 1,
    })["data"]
    started = time.monotonic()
    outline = call("POST", "/novel-ai/generate/outline", {
        "novel_id": novel["id"],
        "total_chapters": 1,
        "generation_mode": "free",
        "free_provider": "deepseek",
    })["data"]
    item = outline["chapters"][0]
    chapter = call("POST", f"/novels/{novel['id']}/chapters", {
        "title": item["title"],
        "chapter_number": item["chapter_number"],
        "synopsis": item["synopsis"],
    })["data"]
    with open(".e2e-clean.json", "w", encoding="utf-8") as handle:
        json.dump({"novel_id": novel["id"], "chapter_id": chapter["id"]}, handle)
    print(json.dumps({
        "step": "outline", "ok": True, "seconds": round(time.monotonic() - started, 1),
        "novel_id": novel["id"], "chapter_id": chapter["id"],
        "outline_count": len(outline["chapters"]), "title": item["title"],
    }, ensure_ascii=False))


def chapter() -> None:
    with open(".e2e-clean.json", encoding="utf-8") as handle:
        ids = json.load(handle)
    started = time.monotonic()
    result = call("POST", f"/novel-ai/generate/chapter/{ids['chapter_id']}", {
        "generation_mode": "free", "free_provider": "deepseek",
        "restart_failed_generation": True,
    })["data"]
    content = result["content"]
    ids["content"] = content
    with open(".e2e-clean.json", "w", encoding="utf-8") as handle:
        json.dump(ids, handle, ensure_ascii=False)
    print(json.dumps({
        "step": "chapter", "ok": True, "seconds": round(time.monotonic() - started, 1),
        "chars": len(content), "paragraphs": len([p for p in content.split("\n\n") if p.strip()]),
        "word_count": result.get("word_count"), "status": result.get("status"),
    }, ensure_ascii=False))


def convert() -> None:
    with open(".e2e-clean.json", encoding="utf-8") as handle:
        ids = json.load(handle)
    started = time.monotonic()
    script = call("POST", "/conversion/novel-to-script", {
        "novel_text": ids["content"], "target_episodes": 1, "style": "悬疑、紧凑",
        "generation_mode": "free", "free_provider": "deepseek",
    })["data"]
    episode = script["episodes"][0]
    storyboard = call("POST", "/conversion/script-to-video", {
        "script_text": episode["script"], "generation_mode": "free", "free_provider": "deepseek",
    })["data"]
    print(json.dumps({
        "step": "conversion", "ok": True, "seconds": round(time.monotonic() - started, 1),
        "episodes": script["total_episodes"], "script_chars": len(episode["script"]),
        "scenes": len(storyboard["scenes"]), "total_duration": storyboard["total_duration"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    globals()[sys.argv[1]]()
