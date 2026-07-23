#!/usr/bin/env python3
"""无控制台 UI 的番茄小说 Playwright 发布器。"""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from playwright.sync_api import (
    BrowserContext,
    Error as PlaywrightError,
    Page,
    TimeoutError,
    sync_playwright,
)


BOOK_MANAGE_URL = "https://fanqienovel.com/main/writer/book-manage"
WRITER_URL = "https://fanqienovel.com/main/writer/"
UPLOAD_PATTERN = re.compile(
    r"^(?:\d+\s+)?第\s*(?P<number>\d+)\s*章[\s_：:-]*(?P<title>.+?)\.txt$"
)
CHROMIUM_ARGS = ["--ignore-certificate-errors"]
DEFAULT_CHAPTERS_PER_MANAGER_PAGE = 15


class PublishError(RuntimeError):
    """发布失败；调用方必须保留当前队列。"""


@dataclass(frozen=True)
class ChapterJob:
    number: int
    title: str
    queued_file: Path
    status: str
    expected_action: str | None = None


@dataclass(frozen=True)
class ParsedChapter:
    number: int
    title: str
    body: str
    path: Path
    expected_action: str | None = None


@dataclass(frozen=True)
class PublishPlanItem:
    job: ChapterJob
    scheduled_at: datetime | None = None
    char_count: int = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def load_jobs(ledger_path: Path) -> list[ChapterJob]:
    data = json.loads(ledger_path.read_text(encoding="utf-8"))
    jobs = []
    for record in data.get("chapters", {}).values():
        queued_file = record.get("queued_file")
        if queued_file:
            jobs.append(
                ChapterJob(
                    number=int(record["number"]),
                    title=str(record.get("title", "")).strip(),
                    queued_file=Path(queued_file),
                    status=str(record.get("status", "unknown")),
                    expected_action=record.get("expected_action"),
                )
            )
    return sorted(jobs, key=lambda item: item.number)


def select_jobs(
    jobs: Iterable[ChapterJob],
    *,
    from_chapter: int | None = None,
    to_chapter: int | None = None,
    count: int | None = None,
) -> list[ChapterJob]:
    selected = [
        item
        for item in jobs
        if item.status == "queued"
        and (from_chapter is None or item.number >= from_chapter)
        and (to_chapter is None or item.number <= to_chapter)
    ]
    selected.sort(key=lambda item: item.number)
    if count is not None:
        if count <= 0:
            raise ValueError("count 必须大于 0")
        selected = selected[:count]
    return selected


def build_publish_plan(
    jobs: list[ChapterJob],
    *,
    runtime_path: Path | None = None,
    schedule: bool = False,
    chapters_per_day: int = 8,
    daily_char_limit: int | None = None,
    existing_day_chars: dict[date, int] | None = None,
    schedule_start_date: str | None = None,
    schedule_time: str = "01:00",
    timezone_name: str = "Asia/Shanghai",
    now: datetime | None = None,
) -> list[PublishPlanItem]:
    if not schedule:
        return [PublishPlanItem(job=item) for item in jobs]
    if chapters_per_day <= 0:
        raise ValueError("chapters_per_day 必须大于 0")
    try:
        tz = ZoneInfo(timezone_name)
    except Exception as exc:
        raise ValueError(f"无效时区：{timezone_name}") from exc
    if schedule_start_date:
        try:
            start_day = date.fromisoformat(schedule_start_date)
        except ValueError as exc:
            raise ValueError("schedule_start_date 必须是 YYYY-MM-DD") from exc
    else:
        start_day = datetime.now(tz).date()
    try:
        hour_text, minute_text = schedule_time.split(":", 1)
        publish_time = datetime_time(int(hour_text), int(minute_text), tzinfo=tz)
    except ValueError as exc:
        raise ValueError("schedule_time 必须是 HH:MM") from exc
    current_time = now or datetime.now(tz)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=tz)
    else:
        current_time = current_time.astimezone(tz)
    earliest_allowed = current_time + timedelta(hours=1)
    while datetime.combine(start_day, publish_time) <= earliest_allowed:
        start_day += timedelta(days=1)
    plan = []
    day_chars = dict(existing_day_chars or {})
    current_day = start_day
    for index, job in enumerate(jobs):
        char_count = 0
        if runtime_path is not None:
            try:
                chapter = parse_upload_file(runtime_path / job.queued_file)
                char_count = len(re.sub(r"\s+", "", chapter.body))
            except Exception:
                char_count = 0
        if daily_char_limit is not None:
            used = day_chars.get(current_day, 0)
            if used > 0 and used + char_count > daily_char_limit:
                current_day += timedelta(days=1)
                while datetime.combine(current_day, publish_time) <= earliest_allowed:
                    current_day += timedelta(days=1)
                used = day_chars.get(current_day, 0)
            publish_day = current_day
            day_chars[publish_day] = used + char_count
        else:
            publish_day = start_day + timedelta(days=index // chapters_per_day)
        scheduled_at = datetime.combine(publish_day, publish_time)
        plan.append(
            PublishPlanItem(job=job, scheduled_at=scheduled_at, char_count=char_count)
        )
    return plan


def print_publish_plan(plan: list[PublishPlanItem]) -> None:
    for item in plan:
        if item.scheduled_at is None:
            print(f"计划：第{item.job.number}章 立即发布")
        else:
            print(
                "计划："
                f"第{item.job.number}章 -> "
                f"{item.scheduled_at.strftime('%Y-%m-%d %H:%M')}"
                f"（{item.char_count}字）"
            )


def parse_upload_file(path: Path, expected_action: str | None = None) -> ParsedChapter:
    match = UPLOAD_PATTERN.match(path.name)
    if not match:
        raise PublishError(f"无法识别待发布文件名：{path.name}")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first is None:
        raise PublishError(f"章节正文为空：{path.name}")
    heading = re.match(r"^第\s*(\d+)\s*章[\s_：:-]*(.*)$", lines[first].strip())
    body_lines = lines[first + 1 :] if heading else lines[first:]
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    body = "\n".join(body_lines).strip()
    if not body:
        raise PublishError(f"章节正文为空：{path.name}")
    return ParsedChapter(
        number=int(match.group("number")),
        title=match.group("title").strip(),
        body=body,
        path=path,
        expected_action=expected_action,
    )


def find_next_button(page: Page):
    button = page.get_by_role("button", name="下一步", exact=True).first
    if button.is_visible():
        return button
    candidates = page.get_by_text("下一步", exact=True)
    for index in range(candidates.count()):
        candidate = candidates.nth(index)
        if candidate.is_visible():
            return candidate
    raise PublishError("未找到“下一步”按钮")


def _click_visible_action(page: Page, label: str) -> bool:
    for selector in ("button", '[role="button"]'):
        candidates = page.locator(selector).filter(has_text=label)
        for index in range(candidates.count()):
            candidate = candidates.nth(index)
            if candidate.is_visible():
                candidate.click(force=True)
                return True
    texts = page.get_by_text(label, exact=True)
    for index in range(texts.count()):
        candidate = texts.nth(index)
        if candidate.is_visible():
            candidate.evaluate(
                """el => {
                    const target = el.closest('button,[role="button"]') || el;
                    target.click();
                }"""
            )
            return True
    return False


def wait_for_publish_button(page: Page, timeout: int = 60000):
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        # The publish button may already be visible before required modal
        # choices are completed. Handle blocking choices first.
        if page.get_by_text("请选择是否使用 AI", exact=False).first.is_visible():
            if not select_ai_usage_no(page):
                raise PublishError("发布设置中未能选中“AI 使用：否”")
            page.wait_for_timeout(500)
            continue
        publish = page.get_by_role("button", name="确认发布", exact=True).first
        if not publish.is_visible():
            publish = page.get_by_text("确认发布", exact=True).first
        if publish.is_visible():
            return publish
        if page.get_by_text("请选择内容检测方式", exact=False).first.is_visible():
            if not _click_visible_action(page, "仅基础检测"):
                raise PublishError("内容检测弹窗缺少“仅基础检测”操作")
            page.wait_for_timeout(500)
            continue
        if page.get_by_text("内容风险检测", exact=False).first.is_visible():
            if not _click_visible_action(page, "取消"):
                raise PublishError("内容风险检测弹窗缺少“取消”操作")
            page.wait_for_timeout(500)
            continue
        typo_submit = page.get_by_role("button", name="提交", exact=True).first
        if typo_submit.is_visible():
            typo_submit.click(force=True)
            page.wait_for_timeout(500)
            continue
        page.wait_for_timeout(250)
    raise PublishError("等待最终发布设置超时")


def select_ai_usage_no(page: Page) -> bool:
    try:
        selected = bool(
            page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const blocks = [...document.querySelectorAll('*')].filter(el =>
                        visible(el) && /是否使用\\s*AI/.test(el.innerText || '')
                    );
                    for (const block of blocks) {
                        const noTexts = [...block.querySelectorAll('label, span, div')].filter(el =>
                            visible(el) && (el.innerText || '').trim() === '否'
                        );
                        for (const node of noTexts) {
                            const rect = node.getBoundingClientRect();
                            const candidates = [
                                node.closest('label,[role="radio"],button,[role="button"]'),
                                node.previousElementSibling,
                                node,
                            ].filter(Boolean);
                            for (const target of candidates) {
                                target.click();
                            }
                            const pointTargets = [
                                document.elementFromPoint(rect.left - 18, rect.top + rect.height / 2),
                                document.elementFromPoint(rect.left - 28, rect.top + rect.height / 2),
                                document.elementFromPoint(rect.left + rect.width / 2, rect.top + rect.height / 2),
                            ].filter(Boolean);
                            for (const target of pointTargets) {
                                for (const name of ['pointerdown', 'mousedown', 'mouseup', 'click']) {
                                    target.dispatchEvent(new MouseEvent(name, {
                                        bubbles: true,
                                        cancelable: true,
                                        clientX: rect.left + rect.width / 2,
                                        clientY: rect.top + rect.height / 2,
                                        view: window,
                                    }));
                                }
                            }
                            return true;
                        }
                        const radios = [...block.querySelectorAll('input[type="radio"]')].filter(visible);
                        if (radios.length >= 2) {
                            radios[1].click();
                            radios[1].dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                    }
                    return false;
                }"""
            )
        )
        if selected:
            page.wait_for_timeout(250)
            return True
    except Exception:
        pass
    candidates = [
        page.locator("label").filter(has_text="否").first,
        page.locator('[role="radio"]').filter(has_text="否").first,
        page.get_by_text("否", exact=True).first,
    ]
    for candidate in candidates:
        try:
            if candidate.is_visible():
                candidate.click(force=True)
                page.wait_for_timeout(250)
                return True
        except Exception:
            continue
    try:
        return bool(
            page.evaluate(
                """() => {
                    const visible = (el) => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        return style && style.display !== 'none' && style.visibility !== 'hidden' && el.getBoundingClientRect().width > 0 && el.getBoundingClientRect().height > 0;
                    };
                    const blocks = [...document.querySelectorAll('*')].filter(el =>
                        visible(el) && (el.innerText || '').includes('是否使用AI')
                    );
                    for (const block of blocks) {
                        const labels = [...block.querySelectorAll('label, span, div')].filter(el =>
                            visible(el) && (el.innerText || '').trim() === '否'
                        );
                        for (const label of labels) {
                            label.click();
                            return true;
                        }
                        const radios = [...block.querySelectorAll('input[type="radio"]')].filter(visible);
                        if (radios.length >= 2) {
                            radios[1].click();
                            radios[1].dispatchEvent(new Event('change', { bubbles: true }));
                            return true;
                        }
                    }
                    return false;
                }"""
            )
        )
    except Exception:
        return False


def _force_fill_input(locator, value: str) -> bool:
    try:
        if not locator.is_visible():
            return False
        locator.click(force=True)
        try:
            locator.fill(value, force=True)
        except Exception:
            locator.evaluate(
                """(el, value) => {
                    el.removeAttribute('readonly');
                    el.value = value;
                    for (const eventName of ['input', 'change', 'blur']) {
                        el.dispatchEvent(new Event(eventName, { bubbles: true }));
                    }
                }""",
                value,
            )
        return True
    except Exception:
        return False


def _fill_first_matching_input(page: Page, selectors: tuple[str, ...], value: str) -> bool:
    for selector in selectors:
        candidates = page.locator(selector)
        for index in range(candidates.count()):
            if _force_fill_input(candidates.nth(index), value):
                return True
    return False


def _fill_single_visible_input(page: Page, selector: str, value: str) -> bool:
    candidates = page.locator(selector)
    visible_indexes = []
    for index in range(candidates.count()):
        try:
            if candidates.nth(index).is_visible():
                visible_indexes.append(index)
        except Exception:
            continue
    if len(visible_indexes) != 1:
        return False
    return _force_fill_input(candidates.nth(visible_indexes[0]), value)


def _setting_label_input(page: Page, label: str):
    labels = page.get_by_text(label, exact=True)
    for index in range(labels.count()):
        candidate = labels.nth(index)
        try:
            if not candidate.is_visible():
                continue
            handle = candidate.element_handle()
            input_handle = page.evaluate_handle(
                """label => {
                    const visible = el => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    let row = label;
                    for (let depth = 0; row && depth < 5; depth += 1, row = row.parentElement) {
                        const inputs = [...row.querySelectorAll('input')].filter(visible);
                        if (inputs.length) return inputs[inputs.length - 1];
                    }
                    let sibling = label.parentElement;
                    for (let depth = 0; sibling && depth < 5; depth += 1, sibling = sibling.parentElement) {
                        let next = sibling.nextElementSibling;
                        while (next) {
                            const inputs = [...next.querySelectorAll('input')].filter(visible);
                            if (inputs.length) return inputs[0];
                            next = next.nextElementSibling;
                        }
                    }
                    return null;
                }""",
                handle,
            )
            if input_handle.as_element():
                return input_handle.as_element()
        except Exception:
            continue
    return None


def _fill_setting_label_input(page: Page, label: str, value: str) -> bool:
    element = _setting_label_input(page, label)
    if element is None:
        return False
    try:
        element.click()
        element.fill(value)
    except Exception:
        try:
            element.evaluate(
                """(el, value) => {
                    el.removeAttribute('readonly');
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    setter.call(el, value);
                    for (const eventName of ['input', 'change', 'blur']) {
                        el.dispatchEvent(new Event(eventName, { bubbles: true }));
                    }
                }""",
                value,
            )
        except Exception:
            return False
    try:
        page.keyboard.press("Enter")
    except Exception:
        pass
    return True


def _scheduled_fields_visible(page: Page) -> bool:
    date_input = _setting_label_input(page, "日期")
    time_input = _setting_label_input(page, "时间")
    return date_input is not None and time_input is not None


def _enable_scheduled_publish(page: Page) -> None:
    if _scheduled_fields_visible(page):
        return
    labels = page.get_by_text("定时发布", exact=True)
    for index in range(labels.count()):
        label = labels.nth(index)
        try:
            if not label.is_visible():
                continue
            handle = label.element_handle()
            clicked = page.evaluate(
                """label => {
                    const visible = el => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    let row = label;
                    for (let depth = 0; row && depth < 6; depth += 1, row = row.parentElement) {
                        const controls = [...row.querySelectorAll(
                            '[role="switch"], button, input[type="checkbox"], [class*="switch"], [class*="Switch"]'
                        )].filter(visible);
                        const target = controls.find(el => !el.innerText || !el.innerText.includes('定时发布'))
                            || controls[controls.length - 1];
                        if (target) {
                            target.click();
                            return true;
                        }
                    }
                    label.click();
                    return true;
                }""",
                handle,
            )
            if clicked:
                page.wait_for_timeout(500)
                if _scheduled_fields_visible(page):
                    return
        except Exception:
            continue
    raise PublishError("发布设置中未能打开“定时发布”开关")


def select_scheduled_publish(page: Page, scheduled_at: datetime) -> None:
    _enable_scheduled_publish(page)
    page.wait_for_timeout(500)
    date_value = scheduled_at.strftime("%Y-%m-%d")
    time_value = scheduled_at.strftime("%H:%M")
    datetime_value = scheduled_at.strftime("%Y-%m-%d %H:%M")
    date_ok = _fill_setting_label_input(page, "日期", date_value)
    time_ok = _fill_setting_label_input(page, "时间", time_value)
    if date_ok and time_ok:
        page.wait_for_timeout(300)
        return
    datetime_selectors = (
        'input[placeholder*="发布时间"]',
        'input[placeholder*="发表时间"]',
        'input[placeholder*="更新时间"]',
        'input[placeholder*="日期时间"]',
        'input[placeholder*="选择日期和时间"]',
    )
    if _fill_first_matching_input(
        page, datetime_selectors, datetime_value
    ) or _fill_single_visible_input(page, 'input[class*="picker"]', datetime_value):
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        return
    date_ok = date_ok or _fill_first_matching_input(
        page,
        (
            'input[type="date"]',
            'input[placeholder*="日期"]',
            'input[placeholder*="年月日"]',
            'input[placeholder*="选择日期"]',
        ),
        date_value,
    )
    time_ok = time_ok or _fill_first_matching_input(
        page,
        (
            'input[type="time"]',
            'input[placeholder*="时间"]',
            'input[placeholder*="时分"]',
            'input[placeholder*="选择时间"]',
        ),
        time_value,
    )
    if date_ok and time_ok:
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        return
    raise PublishError(
        f"未能填写定时发布时间：{date_value} {time_value}，请查看诊断截图"
    )


def click_confirm_publish(page: Page) -> None:
    clicked = page.evaluate(
        """() => {
            const visible = el => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && rect.width > 0
                    && rect.height > 0;
            };
            const controls = [...document.querySelectorAll('button,[role="button"]')]
                .filter(el => visible(el) && (el.innerText || '').trim() === '确认发布');
            const target = controls[controls.length - 1];
            if (!target) return false;
            target.scrollIntoView({ block: 'center', inline: 'center' });
            target.click();
            return true;
        }"""
    )
    if clicked:
        return
    if not _click_visible_action(page, "确认发布"):
        raise PublishError("发布设置中未找到可点击的“确认发布”按钮")


def wait_after_confirm_publish(page: Page, timeout_ms: int = 30000) -> bool:
    success = page.get_by_text(
        re.compile(r"定时发布成功|发布成功|提交成功|发布完成|已提交|提交审核")
    ).first
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        try:
            if success.is_visible():
                return True
        except Exception:
            pass
        try:
            publish_settings = page.get_by_text("发布设置", exact=True).first
            confirm = page.get_by_text("确认发布", exact=True).first
            if not publish_settings.is_visible() and not confirm.is_visible():
                return True
        except Exception:
            pass
        page.wait_for_timeout(500)
    return False


def _write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def mark_processed(
    *,
    runtime_path: Path,
    ledger_path: Path,
    job: ChapterJob,
    book: str,
    now: str,
    scheduled_at: datetime | None = None,
) -> Path:
    source = runtime_path / job.queued_file
    if not source.is_file():
        raise FileNotFoundError(source)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    record = ledger["chapters"].get(str(job.number))
    if not record:
        raise PublishError(f"台账缺少第{job.number}章")
    destination = runtime_path / "uploaded" / book / source.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        stamp = re.sub(r"[^0-9A-Za-z]+", "", now)
        for index in range(1, 1000):
            candidate = destination.with_name(
                f"{destination.stem}-{stamp}-{index}{destination.suffix}"
            )
            if not candidate.exists():
                destination = candidate
                break
        else:
            raise PublishError(f"无法生成不冲突的归档文件名：{destination}")
    shutil.move(str(source), str(destination))
    record.update(
        {
            "status": "processed",
            "processed_at": now,
            "archive_file": destination.relative_to(runtime_path).as_posix(),
        }
    )
    if scheduled_at is not None:
        record["publish_mode"] = "scheduled"
        record["scheduled_publish_at"] = scheduled_at.isoformat(timespec="minutes")
    else:
        record["publish_mode"] = "immediate"
    ledger["updated_at"] = now
    _write_json_atomic(ledger_path, ledger)
    return destination


def mark_verified(
    *,
    ledger_path: Path,
    from_chapter: int,
    to_chapter: int,
    platform_latest: int,
    platform_total: int,
    now: str,
) -> list[int]:
    if platform_latest < to_chapter or platform_total < to_chapter:
        raise PublishError(
            f"平台证据不足：最新第{platform_latest}章，共{platform_total}章"
        )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    verified = []
    for number in range(from_chapter, to_chapter + 1):
        record = ledger.get("chapters", {}).get(str(number))
        if not record:
            raise PublishError(f"台账缺少第{number}章")
        if record.get("status") not in ("processed", "verified"):
            raise PublishError(f"第{number}章尚未 processed，不能核验")
        record.update(
            {
                "status": "verified",
                "verified_at": now,
                "platform_latest_chapter": platform_latest,
                "platform_total_chapters": platform_total,
            }
        )
        verified.append(number)
    ledger["updated_at"] = now
    _write_json_atomic(ledger_path, ledger)
    return verified


def load_chapter_char_counts(ledger_path: Path, runtime_path: Path) -> dict[int, int]:
    project_root = ledger_path.parent.parent
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    counts: dict[int, int] = {}
    for number_text, record in ledger.get("chapters", {}).items():
        try:
            number = int(number_text)
        except ValueError:
            continue
        candidates = []
        source = record.get("source")
        if source:
            candidates.append(project_root / source)
        queued_file = record.get("queued_file")
        if queued_file:
            candidates.append(runtime_path / queued_file)
        archive_file = record.get("archive_file")
        if archive_file:
            candidates.append(runtime_path / archive_file)
        for path in candidates:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8-sig")
            except OSError:
                continue
            lines = text.splitlines()
            first = next((index for index, line in enumerate(lines) if line.strip()), None)
            if first is None:
                continue
            body = "\n".join(lines[first + 1 :]).strip()
            counts[number] = len(re.sub(r"\s+", "", body))
            break
    return counts


def summarize_existing_day_chars(
    scheduled_items: list[tuple[int, date]],
    char_counts: dict[int, int],
) -> dict[date, int]:
    result: dict[date, int] = {}
    for number, scheduled_day in scheduled_items:
        result[scheduled_day] = result.get(scheduled_day, 0) + char_counts.get(number, 0)
    return result


def inspect_platform(
    *, state_path: Path, book: str, headless: bool = False
) -> tuple[int, int, str]:
    if not state_path.is_file():
        raise PublishError(f"缺少登录状态：{state_path}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=CHROMIUM_ARGS)
        context = browser.new_context(storage_state=str(state_path))
        page = context.new_page()
        try:
            page.goto(BOOK_MANAGE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
            if "login" in page.url:
                raise PublishError("登录状态已失效，请重新执行 login")
            cards = page.locator("div, li, section, article").filter(has_text=book)
            card_text = ""
            for index in range(cards.count() - 1, -1, -1):
                candidate = cards.nth(index)
                try:
                    if candidate.is_visible():
                        text = candidate.inner_text()
                        if book in text and ("最近更新" in text or "章节管理" in text):
                            card_text = text
                            break
                except Exception:
                    continue
            if not card_text:
                body = page.locator("body").inner_text()
                if book not in body:
                    raise PublishError(f"作品管理页未找到《{book}》")
                card_text = body
            latest_match = re.search(r"最近更新[：:]\s*第\s*(\d+)\s*章", card_text)
            total_matches = [
                int(value) for value in re.findall(r"(?:^|\s)(\d+)\s*章(?:\s|$)", card_text)
            ]
            if not latest_match or not total_matches:
                raise PublishError("作品管理页缺少最新章节或总章节数")
            return int(latest_match.group(1)), max(total_matches), card_text
        finally:
            context.close()
            browser.close()


def login(state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False, args=CHROMIUM_ARGS)
        context_args = {"storage_state": str(state_path)} if state_path.is_file() else {}
        context = browser.new_context(**context_args)
        page = context.new_page()
        errors = []
        for url in (
            "https://fanqienovel.com/main/writer/?enter_from=author_zone",
            WRITER_URL,
            "https://fanqienovel.com/writer",
        ):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as exc:
                errors.append(f"{url} -> {exc}")
        if errors and len(errors) == 3:
            print("自动打开番茄作者后台失败，但浏览器窗口会保持打开。")
            print("请在地址栏手动尝试以下地址之一：")
            print("1. https://fanqienovel.com/main/writer/?enter_from=author_zone")
            print("2. https://fanqienovel.com/main/writer/")
            print("3. https://fanqienovel.com/writer")
            print("失败记录：")
            for item in errors:
                print(f"- {item}")
        print("请在浏览器完成番茄登录，看到作家后台后回到终端按回车。")
        input()
        context.storage_state(path=str(state_path))
        context.close()
        browser.close()


class FanqiePublisher:
    def __init__(self, context: BrowserContext, book: str, diagnostics_dir: Path):
        self.context = context
        self.book = book
        self.page = context.new_page()
        self.diagnostics_dir = diagnostics_dir
        self.last_editor_action = "unknown"

    @staticmethod
    def _dismiss_popups(page: Page) -> None:
        for _ in range(3):
            page.keyboard.press("Escape")
            page.wait_for_timeout(150)
        for label in ("我知道了", "跳过", "完成"):
            locator = page.get_by_text(label, exact=True)
            try:
                count = locator.count()
            except Exception:
                continue
            for index in range(count):
                try:
                    candidate = locator.nth(index)
                    box = candidate.bounding_box()
                    if box and box["y"] > 100:
                        candidate.click(force=True)
                except Exception:
                    continue

    def _is_manager_page(self, page: Page) -> bool:
        create_button = page.get_by_role("button", name="新建章节").first
        if create_button.is_visible():
            return True
        create_text = page.get_by_text("新建章节", exact=True).first
        if create_text.is_visible():
            return True
        chapter_rows = page.locator("tr, li, .chapter-item")
        try:
            return chapter_rows.count() > 0 and self.book in page.locator("body").inner_text()
        except Exception:
            return False

    def _locate_book_card(self, page: Page):
        cards = page.locator("div, li, section, article").filter(has_text=self.book)
        for index in range(cards.count() - 1, -1, -1):
            card = cards.nth(index)
            try:
                if not card.is_visible():
                    continue
                card.hover(timeout=2500)
                button = card.get_by_text("章节管理").first
                if button.is_visible():
                    return card, button
            except Exception:
                continue
        return None, None

    def _wait_for_manual_manager(self, timeout_ms: int = 600000) -> Page:
        print("自动进入章节管理页失败，浏览器窗口会保留。")
        print("请手动进入作品后台，并打开本书的“章节管理”页面。")
        deadline = time.monotonic() + timeout_ms / 1000
        last_hint = 0.0
        while time.monotonic() < deadline:
            if not self.context.pages:
                raise PublishError("浏览器页面已关闭；章节仍保留 queued，可重新运行 publish")
            page = self.context.pages[-1]
            if page.is_closed():
                raise PublishError("浏览器页面已关闭；章节仍保留 queued，可重新运行 publish")
            self._dismiss_popups(page)
            if self._is_manager_page(page):
                return page
            try:
                _, button = self._locate_book_card(page)
            except Exception:
                button = None
            if button is not None:
                before = len(self.context.pages)
                button.click(force=True)
                page.wait_for_timeout(2500)
                candidate = self.context.pages[-1] if len(self.context.pages) > before else page
                if self._is_manager_page(candidate):
                    return candidate
            now = time.monotonic()
            if now - last_hint > 20:
                print(f"仍在等待手动进入章节管理页，当前 URL：{page.url}")
                last_hint = now
            try:
                page.wait_for_timeout(1000)
            except PlaywrightError as exc:
                raise PublishError("浏览器页面已关闭；章节仍保留 queued，可重新运行 publish") from exc
        raise PublishError("等待手动进入章节管理页超时")

    def _open_chapter_manager(self) -> Page:
        try:
            self.page.goto(BOOK_MANAGE_URL, wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(2500)
            if "login" in self.page.url:
                raise PublishError("登录状态已失效，请重新执行 login")
            if self._is_manager_page(self.page):
                return self.page
            _, button = self._locate_book_card(self.page)
            if button is not None:
                before = len(self.context.pages)
                button.click(force=True)
                self.page.wait_for_timeout(2500)
                candidate = self.context.pages[-1] if len(self.context.pages) > before else self.page
                if self._is_manager_page(candidate):
                    return candidate
            raise PublishError(f"未找到《{self.book}》的章节管理入口")
        except Exception:
            return self._wait_for_manual_manager()

    @staticmethod
    def inspect_scheduled_chapters(manager: Page) -> list[tuple[int, date]]:
        try:
            manager.wait_for_load_state("domcontentloaded", timeout=60000)
        except Exception:
            pass
        texts = manager.evaluate(
            """() => {
                const visible = el => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                };
                const nodes = [...document.querySelectorAll('tr, li, [class*=chapter], [class*=Chapter], div')];
                const seen = new Set();
                const result = [];
                for (const node of nodes) {
                    if (!visible(node)) continue;
                    const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                    if (!text || seen.has(text)) continue;
                    if (!/第\\s*\\d+\\s*章/.test(text)) continue;
                    if (!/20\\d{2}[-年/]\\d{1,2}[-月/]\\d{1,2}/.test(text)) continue;
                    if (!/(定时|预计|发布时间|审核|待发布|发布)/.test(text)) continue;
                    seen.add(text);
                    result.push(text);
                    if (result.length >= 300) break;
                }
                return result;
            }"""
        )
        scheduled = []
        for text in texts:
            number_match = re.search(r"第\s*(\d+)\s*章", text)
            date_match = re.search(
                r"(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})", text
            )
            if not number_match or not date_match:
                continue
            year, month, day = (int(value) for value in date_match.groups())
            try:
                scheduled.append((int(number_match.group(1)), date(year, month, day)))
            except ValueError:
                continue
        deduped = {}
        for number, scheduled_day in scheduled:
            deduped[number] = scheduled_day
        return sorted(deduped.items(), key=lambda item: item[0])

    @staticmethod
    def _find_existing_chapter_edit(manager: Page, chapter: ParsedChapter) -> bool:
        return bool(
            manager.evaluate(
                """chapter => {
                    const visible = el => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const chapterNumber = chapter.number;
                    const chapterTitle = (chapter.title || '').trim();
                    const numberPattern = new RegExp(`第\\\\s*0*${chapterNumber}\\\\s*章`);
                    const editSelector = '.auto-editor-chapter-edit, .icon-edit, .tomato-edit, [class*="editor-chapter-edit"], [class*="icon-edit"]';
                    const selectors = [
                        'tr',
                        'li',
                        'div',
                        '.chapter-item',
                        '[class*="chapter"]',
                        '[class*="Chapter"]',
                    ];
                    const seen = new Set();
                    const candidates = [];
                    for (const selector of selectors) {
                        for (const node of document.querySelectorAll(selector)) {
                            if (seen.has(node) || !visible(node)) continue;
                            seen.add(node);
                            const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                            if (!numberPattern.test(text) && (!chapterTitle || !text.includes(chapterTitle))) {
                                continue;
                            }
                            const rect = node.getBoundingClientRect();
                            const chapterMatches = [...text.matchAll(/第\s*\d+\s*章/g)].length;
                            const controls = [...node.querySelectorAll(
                                'button, a, [role="button"], svg, i'
                            )].filter(visible);
                            const hasEditIcon = !!node.querySelector(editSelector);
                            candidates.push({
                                node,
                                text,
                                controls,
                                area: rect.width * rect.height,
                                chapterMatches,
                                hasTargetTitle: !!chapterTitle && text.includes(chapterTitle),
                                hasEditIcon,
                                hasEditText: /(编辑|修改|继续写|查看)/.test(text),
                            });
                        }
                    }
                    candidates.sort((left, right) => {
                        if (left.hasEditIcon !== right.hasEditIcon) {
                            return left.hasEditIcon ? -1 : 1;
                        }
                        if (left.hasTargetTitle !== right.hasTargetTitle) {
                            return left.hasTargetTitle ? -1 : 1;
                        }
                        if (left.chapterMatches !== right.chapterMatches) {
                            return left.chapterMatches - right.chapterMatches;
                        }
                        if (left.hasEditText !== right.hasEditText) {
                            return left.hasEditText ? -1 : 1;
                        }
                        if (left.controls.length !== right.controls.length) {
                            return right.controls.length - left.controls.length;
                        }
                        return left.area - right.area;
                    });
                    const entry = candidates[0];
                    if (!entry) return false;
                    return true;
                }""",
                {"number": chapter.number, "title": chapter.title},
            )
        )

    @staticmethod
    def _click_existing_chapter_edit(manager: Page, chapter: ParsedChapter) -> bool:
        row_handle = manager.evaluate_handle(
            """chapter => {
                const visible = el => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                };
                const chapterNumber = chapter.number;
                const chapterTitle = (chapter.title || '').trim();
                const numberPattern = new RegExp(`第\\\\s*0*${chapterNumber}\\\\s*章`);
                const editSelector = '.auto-editor-chapter-edit, .icon-edit, .tomato-edit, [class*="editor-chapter-edit"], [class*="icon-edit"]';
                const selectors = [
                    'tr',
                    'li',
                    'div',
                    '.chapter-item',
                    '[class*="chapter"]',
                    '[class*="Chapter"]',
                ];
                const seen = new Set();
                const candidates = [];
                for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                        if (seen.has(node) || !visible(node)) continue;
                        seen.add(node);
                        const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                        if (!numberPattern.test(text) && (!chapterTitle || !text.includes(chapterTitle))) {
                            continue;
                        }
                        let row = node;
                        for (let depth = 0; row && depth < 8; depth += 1, row = row.parentElement) {
                            if (!visible(row)) continue;
                            if (row.querySelector(editSelector)) {
                                break;
                            }
                        }
                        if (!row || !visible(row) || !row.querySelector(editSelector)) {
                            row = node;
                        }
                        const rect = row.getBoundingClientRect();
                        const rowText = (row.innerText || '').replace(/\\s+/g, ' ').trim();
                        const chapterMatches = [...text.matchAll(/第\s*\d+\s*章/g)].length;
                        candidates.push({
                            node: row,
                            text: rowText,
                            area: rect.width * rect.height,
                            chapterMatches: [...rowText.matchAll(/第\s*\d+\s*章/g)].length || chapterMatches,
                            hasTargetTitle: !!chapterTitle && rowText.includes(chapterTitle),
                            hasEditText: /(编辑|修改|继续写|查看)/.test(rowText),
                            hasEditIcon: !!row.querySelector(editSelector),
                        });
                    }
                }
                candidates.sort((left, right) => {
                    if (left.hasEditIcon !== right.hasEditIcon) {
                        return left.hasEditIcon ? -1 : 1;
                    }
                    if (left.hasTargetTitle !== right.hasTargetTitle) {
                        return left.hasTargetTitle ? -1 : 1;
                    }
                    if (left.chapterMatches !== right.chapterMatches) {
                        return left.chapterMatches - right.chapterMatches;
                    }
                    if (left.hasEditText !== right.hasEditText) {
                        return left.hasEditText ? -1 : 1;
                    }
                    return left.area - right.area;
                });
                return candidates[0]?.node || null;
            }""",
            {"number": chapter.number, "title": chapter.title},
        )
        row = row_handle.as_element()
        if row is None:
            return False
        try:
            row.hover(timeout=3000)
            manager.wait_for_timeout(300)
        except Exception:
            pass
        clicked = bool(
            row.evaluate(
                """node => {
                    const visible = el => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const icon = node.querySelector(
                        '.auto-editor-chapter-edit, .icon-edit, .tomato-edit, [class*="editor-chapter-edit"], [class*="icon-edit"]'
                    );
                    if (icon && visible(icon)) {
                        icon.scrollIntoView({ block: 'center', inline: 'center' });
                        icon.click();
                        return true;
                    }
                    const controls = [...node.querySelectorAll('button, a, [role="button"], span, i, svg')]
                        .filter(visible);
                    const preferred = controls.find(el =>
                        /(编辑|修改|继续写|查看)/.test((el.innerText || '').trim())
                        || /auto-editor-chapter-edit|icon-edit|tomato-edit/.test(el.className || '')
                    );
                    if (preferred) {
                        preferred.scrollIntoView({ block: 'center', inline: 'center' });
                        preferred.click();
                        return true;
                    }
                    return false;
                }"""
            )
        )
        if not clicked:
            raise PublishError(f"已定位第{chapter.number}章，但未找到可点击的编辑图标")
        return True

    @staticmethod
    def _search_chapter_in_manager(
        manager: Page, chapter: ParsedChapter, *, click: bool = True
    ) -> bool:
        search_terms = [
            f"第{chapter.number}章",
            str(chapter.number),
            chapter.title,
        ]
        search_selectors = (
            'input[placeholder*="搜索"]',
            'input[placeholder*="章节"]',
            'input[placeholder*="标题"]',
            'input[type="search"]',
        )
        for term in search_terms:
            if not term:
                continue
            for selector in search_selectors:
                inputs = manager.locator(selector)
                for index in range(inputs.count()):
                    candidate = inputs.nth(index)
                    try:
                        if not candidate.is_visible():
                            continue
                        candidate.fill(term, force=True)
                        try:
                            candidate.press("Enter")
                        except Exception:
                            pass
                        search_button = manager.get_by_text("搜索", exact=True).first
                        if search_button.is_visible():
                            search_button.click(force=True)
                        manager.wait_for_timeout(1200)
                        found = (
                            FanqiePublisher._click_existing_chapter_edit(manager, chapter)
                            if click
                            else FanqiePublisher._find_existing_chapter_edit(manager, chapter)
                        )
                        if found:
                            return True
                    except Exception:
                        continue
        return False

    @staticmethod
    def _latest_chapter_number_on_manager(manager: Page) -> int | None:
        numbers = manager.evaluate(
            r"""() => {
                const text = document.body ? document.body.innerText || '' : '';
                return [...text.matchAll(/第\s*(\d+)\s*章/g)].map(match => Number(match[1]));
            }"""
        )
        parsed = [int(number) for number in numbers if int(number) > 0]
        return max(parsed) if parsed else None

    @staticmethod
    def _visible_chapter_numbers(manager: Page) -> list[int]:
        numbers = manager.evaluate(
            r"""() => {
                const visible = el => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                };
                const nodes = [...document.querySelectorAll(
                    'tr, li, .chapter-item, [class*="chapter"], [class*="Chapter"]'
                )].filter(visible);
                const result = [];
                const seenText = new Set();
                for (const node of nodes) {
                    const text = (node.innerText || '').replace(/\s+/g, ' ').trim();
                    if (!text || seenText.has(text) || text.length > 500) continue;
                    seenText.add(text);
                    const match = text.match(/第\s*(\d+)\s*章/);
                    if (match) result.push(Number(match[1]));
                }
                if (result.length) return result;
                const body = document.body ? document.body.innerText || '' : '';
                return [...body.matchAll(/第\s*(\d+)\s*章/g)].map(match => Number(match[1]));
            }"""
        )
        result = []
        for number in numbers:
            parsed = int(number)
            if parsed > 0 and (not result or result[-1] != parsed):
                result.append(parsed)
        return result

    @staticmethod
    def _active_page_number(manager: Page) -> int | None:
        active = manager.evaluate(
            r"""() => {
                const visible = el => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                };
                const controls = [...document.querySelectorAll('button, a, [role="button"], li, span')]
                    .filter(visible);
                const active = controls.find(el => {
                    const text = (el.innerText || '').trim();
                    if (!/^\d+$/.test(text)) return false;
                    const cls = String(el.className || '').toLowerCase();
                    return el.getAttribute('aria-current') === 'page'
                        || el.getAttribute('aria-selected') === 'true'
                        || cls.includes('active')
                        || cls.includes('current')
                        || cls.includes('selected');
                });
                return active ? Number((active.innerText || '').trim()) : null;
            }"""
        )
        return int(active) if active else None

    @staticmethod
    def _click_page_number(manager: Page, page_number: int) -> bool:
        if page_number <= 0:
            return False
        clicked = bool(
            manager.evaluate(
                """targetPage => {
                    const visible = el => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const controls = [...document.querySelectorAll('button, a, [role="button"], li, div, span')]
                        .filter(el => visible(el) && (el.innerText || '').trim() === String(targetPage));
                    const target = controls[controls.length - 1];
                    if (!target) return false;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    target.click();
                    return true;
                }""",
                page_number,
            )
        )
        if clicked:
            manager.wait_for_timeout(1500)
        return clicked

    @staticmethod
    def _click_pagination_step(manager: Page, direction: int) -> bool:
        clicked = bool(
            manager.evaluate(
                r"""direction => {
                    const visible = el => {
                        if (!el) return false;
                        const style = window.getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.display !== 'none'
                            && style.visibility !== 'hidden'
                            && rect.width > 0
                            && rect.height > 0;
                    };
                    const disabled = el => {
                        const cls = String(el.className || '').toLowerCase();
                        return el.disabled
                            || el.getAttribute('aria-disabled') === 'true'
                            || cls.includes('disabled');
                    };
                    const controls = [...document.querySelectorAll(
                        'button, a, [role="button"], li, div, span'
                    )].filter(el => visible(el) && !disabled(el));
                    const matches = controls.filter(el => {
                        const text = [
                            el.innerText || '',
                            el.getAttribute('aria-label') || '',
                            el.getAttribute('title') || '',
                            el.textContent || '',
                        ].join(' ').replace(/\s+/g, ' ').trim();
                        if (direction > 0) {
                            return /下一页|下页|next|>|›|»/i.test(text);
                        }
                        return /上一页|上页|prev|previous|<|‹|«/i.test(text);
                    });
                    const target = direction > 0 ? matches[matches.length - 1] : matches[0];
                    if (!target) return false;
                    target.scrollIntoView({ block: 'center', inline: 'center' });
                    target.click();
                    return true;
                }""",
                1 if direction > 0 else -1,
            )
        )
        if clicked:
            manager.wait_for_timeout(1500)
        return clicked

    @staticmethod
    def _chapter_page_candidates(manager: Page, chapter: ParsedChapter) -> list[int]:
        target_pages: list[int] = []
        visible_numbers = FanqiePublisher._visible_chapter_numbers(manager)
        active_page = FanqiePublisher._active_page_number(manager) or 1
        unique_visible = list(dict.fromkeys(visible_numbers))
        if chapter.number in unique_visible:
            target_pages.append(active_page)
        elif len(unique_visible) >= 2:
            first, last = unique_visible[0], unique_visible[-1]
            minimum, maximum = min(unique_visible), max(unique_visible)
            descending = first > last
            if descending:
                if chapter.number < minimum:
                    offset = 1 + (minimum - chapter.number - 1) // DEFAULT_CHAPTERS_PER_MANAGER_PAGE
                    target_pages.append(active_page + offset)
                elif chapter.number > maximum:
                    offset = 1 + (chapter.number - maximum - 1) // DEFAULT_CHAPTERS_PER_MANAGER_PAGE
                    target_pages.append(active_page - offset)
            else:
                if chapter.number > maximum:
                    offset = 1 + (chapter.number - maximum - 1) // DEFAULT_CHAPTERS_PER_MANAGER_PAGE
                    target_pages.append(active_page + offset)
                elif chapter.number < minimum:
                    offset = 1 + (minimum - chapter.number - 1) // DEFAULT_CHAPTERS_PER_MANAGER_PAGE
                    target_pages.append(active_page - offset)
        if not target_pages:
            latest = FanqiePublisher._latest_chapter_number_on_manager(manager)
            if latest is not None and chapter.number <= latest:
                target_pages.append(
                    (latest - chapter.number) // DEFAULT_CHAPTERS_PER_MANAGER_PAGE + 1
                )
            target_pages.append((chapter.number - 1) // DEFAULT_CHAPTERS_PER_MANAGER_PAGE + 1)
        target_pages = [page for page in target_pages if page > 0]
        return list(dict.fromkeys(target_pages))

    @staticmethod
    def _visible_page_numbers(manager: Page) -> list[int]:
        numbers = manager.evaluate(
            r"""() => {
                const visible = el => {
                    if (!el) return false;
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style.display !== 'none'
                        && style.visibility !== 'hidden'
                        && rect.width > 0
                        && rect.height > 0;
                };
                const controls = [...document.querySelectorAll('button, a, [role="button"], li, span')]
                    .filter(visible)
                    .map(el => (el.innerText || '').trim())
                    .filter(text => /^\d+$/.test(text))
                    .map(text => Number(text))
                    .filter(number => number > 0 && number < 1000);
                return [...new Set(controls)].sort((left, right) => left - right);
            }"""
        )
        return [int(number) for number in numbers]

    @staticmethod
    def _find_existing_chapter_after_paging(
        manager: Page, chapter: ParsedChapter, *, click: bool
    ) -> bool:
        page_numbers = FanqiePublisher._chapter_page_candidates(manager, chapter)
        for page_number in page_numbers:
            if not FanqiePublisher._click_page_number(manager, page_number):
                continue
            found = (
                FanqiePublisher._click_existing_chapter_edit(manager, chapter)
                if click
                else FanqiePublisher._find_existing_chapter_edit(manager, chapter)
            )
            if found:
                return True
        return FanqiePublisher._find_existing_chapter_by_step_paging(
            manager, chapter, click=click
        )

    @staticmethod
    def _find_existing_chapter_by_step_paging(
        manager: Page, chapter: ParsedChapter, *, click: bool
    ) -> bool:
        seen_ranges: set[tuple[int, ...]] = set()
        for _ in range(30):
            visible_numbers = FanqiePublisher._visible_chapter_numbers(manager)
            current_range = tuple(visible_numbers)
            if current_range in seen_ranges:
                return False
            if current_range:
                seen_ranges.add(current_range)
            if chapter.number in visible_numbers:
                found = (
                    FanqiePublisher._click_existing_chapter_edit(manager, chapter)
                    if click
                    else FanqiePublisher._find_existing_chapter_edit(manager, chapter)
                )
                if found:
                    return True
            if len(visible_numbers) < 2:
                return False
            first, last = visible_numbers[0], visible_numbers[-1]
            minimum, maximum = min(visible_numbers), max(visible_numbers)
            descending = first > last
            if descending:
                if chapter.number < minimum:
                    direction = 1
                elif chapter.number > maximum:
                    direction = -1
                else:
                    return False
            else:
                if chapter.number > maximum:
                    direction = 1
                elif chapter.number < minimum:
                    direction = -1
                else:
                    return False
            if not FanqiePublisher._click_pagination_step(manager, direction):
                return False
        return False

    def detect_chapter_action(self, manager: Page, chapter: ParsedChapter) -> str:
        if self._find_existing_chapter_edit(manager, chapter):
            return "edit"
        if self._find_existing_chapter_after_paging(manager, chapter, click=False):
            return "edit"
        if self._search_chapter_in_manager(manager, chapter, click=False):
            return "edit"
        latest = self._latest_chapter_number_on_manager(manager)
        if latest is not None and chapter.number <= latest:
            return "edit"
        return "new"

    def _open_editor(self, manager: Page, chapter: ParsedChapter) -> Page:
        before = len(self.context.pages)
        latest = self._latest_chapter_number_on_manager(manager)
        should_edit = chapter.expected_action == "edit" or (
            latest is not None and chapter.number <= latest
        )
        self.last_editor_action = "edit"
        if not self._click_existing_chapter_edit(manager, chapter):
            if self._find_existing_chapter_after_paging(manager, chapter, click=True):
                manager.wait_for_timeout(2500)
                editor = self.context.pages[-1] if len(self.context.pages) > before else manager
                try:
                    editor.wait_for_load_state("domcontentloaded", timeout=60000)
                except Exception:
                    pass
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        if (
                            editor.locator('input[type="text"]').count() > 0
                            or editor.locator('[contenteditable="true"]').count() > 0
                        ):
                            break
                    except Exception:
                        pass
                    editor.wait_for_timeout(500)
                self._dismiss_popups(editor)
                return editor
            if self._search_chapter_in_manager(manager, chapter):
                manager.wait_for_timeout(2500)
                editor = self.context.pages[-1] if len(self.context.pages) > before else manager
                try:
                    editor.wait_for_load_state("domcontentloaded", timeout=60000)
                except Exception:
                    pass
                deadline = time.monotonic() + 60
                while time.monotonic() < deadline:
                    try:
                        if (
                            editor.locator('input[type="text"]').count() > 0
                            or editor.locator('[contenteditable="true"]').count() > 0
                        ):
                            break
                    except Exception:
                        pass
                    editor.wait_for_timeout(500)
                self._dismiss_popups(editor)
                return editor
            if should_edit:
                raise PublishError(
                    f"第{chapter.number}章应覆盖修改（后台最大章数：{latest or '未知'}），"
                    "但未找到修改入口，已停止避免重复新增"
                )
            self.last_editor_action = "new"
            button = manager.get_by_role("button", name="新建章节").first
            if not button.is_visible():
                button = manager.get_by_text("新建章节", exact=True).first
            if not button.is_visible():
                raise PublishError("未找到“新建章节”按钮")
            button.click(force=True)
        manager.wait_for_timeout(2500)
        editor = self.context.pages[-1] if len(self.context.pages) > before else manager
        try:
            editor.wait_for_load_state("domcontentloaded", timeout=60000)
        except Exception:
            pass
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                if (
                    editor.locator('input[type="text"]').count() > 0
                    or editor.locator('[contenteditable="true"]').count() > 0
                ):
                    break
            except Exception:
                pass
            editor.wait_for_timeout(500)
        self._dismiss_popups(editor)
        return editor

    @staticmethod
    def _fill(editor: Page, chapter: ParsedChapter) -> None:
        number = editor.locator('input[type="text"]').first
        if not number.is_visible():
            raise PublishError("未找到章节序号输入框")
        number.fill(str(chapter.number), force=True)
        title = editor.get_by_placeholder("请输入标题", exact=False).first
        if not title.is_visible():
            title = editor.get_by_placeholder("请输入章节名", exact=False).first
        if not title.is_visible():
            title = editor.locator('input[type="text"]').last
        if not title.is_visible():
            raise PublishError("未找到章节标题输入框")
        title.fill(chapter.title, force=True)
        body = editor.locator(".ql-editor").first
        if not body.is_visible():
            body = editor.locator(".ProseMirror").first
        if not body.is_visible():
            body = editor.locator('[contenteditable="true"]').first
        if not body.is_visible():
            raise PublishError("未找到正文编辑器")
        body.evaluate(
            """(el, text) => {
                el.innerText = text;
                el.dispatchEvent(new InputEvent(
                    'input', {bubbles: true, inputType: 'insertText', data: text}
                ));
            }""",
            chapter.body,
        )

    @staticmethod
    def _editor_matches_chapter(editor: Page, chapter: ParsedChapter) -> bool:
        title = re.sub(r"\s+", "", chapter.title)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            parts = []
            try:
                identity = editor.evaluate(
                    """() => {
                        const visible = el => {
                            if (!el) return false;
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style.display !== 'none'
                                && style.visibility !== 'hidden'
                                && rect.width > 0
                                && rect.height > 0;
                        };
                        return [...document.querySelectorAll('input, textarea')]
                            .filter(visible)
                            .map(el => el.value || el.innerText || el.textContent || '');
                    }"""
                )
                values = [str(value).strip() for value in identity if str(value).strip()]
                for value in values:
                    compact_value = re.sub(r"\s+", "", value)
                    if compact_value.isdigit() and int(compact_value) == chapter.number:
                        return True
                    if re.fullmatch(rf"第?0*{chapter.number}章?", compact_value):
                        return True
                parts.extend(values)
            except Exception:
                pass
            try:
                parts.append(editor.locator("body").inner_text(timeout=2000))
            except Exception:
                pass
            try:
                parts.append(
                    editor.evaluate(
                        """() => [
                            document.body?.innerText || '',
                            document.body?.textContent || '',
                            ...[...document.querySelectorAll('input, textarea')]
                                .map(el => el.value || el.textContent || ''),
                            ...[...document.querySelectorAll('[contenteditable="true"]')]
                                .map(el => el.innerText || el.textContent || ''),
                        ].join('\\n')"""
                    )
                )
            except Exception:
                pass
            try:
                values = editor.locator("input, textarea").evaluate_all(
                    "els => els.map(el => el.value || el.innerText || '')"
                )
                parts.extend(str(value) for value in values)
            except Exception:
                pass
            raw_text = "\n".join(parts)
            if re.search(rf"第\s*0*{chapter.number}\s*章", raw_text) is not None:
                return True
            normalized = re.sub(r"\s+", "", raw_text)
            if re.search(rf"第0*{chapter.number}章", normalized) is not None:
                return True
            if title and title in normalized:
                return True
            editor.wait_for_timeout(500)
        return False

    @staticmethod
    def _submit(
        editor: Page,
        chapter: ParsedChapter,
        scheduled_at: datetime | None = None,
        *,
        require_schedule: bool = True,
    ) -> None:
        find_next_button(editor).click(force=True)
        for _ in range(10):
            if select_ai_usage_no(editor):
                break
            editor.wait_for_timeout(200)
        last_error: TimeoutError | None = None
        scheduled_configured = False
        for _ in range(3):
            publish = wait_for_publish_button(editor)
            if not select_ai_usage_no(editor):
                raise PublishError("发布设置中未能选中“AI 使用：否”")
            if scheduled_at is not None and not scheduled_configured:
                if not require_schedule:
                    scheduled_configured = True
                elif editor.get_by_text("定时发布", exact=True).first.is_visible():
                    select_scheduled_publish(editor, scheduled_at)
                    scheduled_configured = True
                    if not select_ai_usage_no(editor):
                        raise PublishError("发布设置中未能选中“AI 使用：否”")
                    publish = wait_for_publish_button(editor)
                else:
                    scheduled_configured = True
            del publish
            click_confirm_publish(editor)
            try:
                if wait_after_confirm_publish(editor):
                    return
            except TimeoutError as exc:
                last_error = exc
            editor.wait_for_timeout(1500)
        raise PublishError(f"第{chapter.number}章点击确认后未观察到成功反馈") from last_error

    def publish(self, chapter: ParsedChapter, scheduled_at: datetime | None = None) -> None:
        manager = self._open_chapter_manager()
        editor = self._open_editor(manager, chapter)
        try:
            if self.last_editor_action == "edit" and not self._editor_matches_chapter(
                editor, chapter
            ):
                raise PublishError(
                    f"第{chapter.number}章编辑入口打开后章号不匹配，已停止避免误改"
                )
            self._fill(editor, chapter)
            self._submit(
                editor,
                chapter,
                scheduled_at,
                require_schedule=self.last_editor_action != "edit",
            )
        except Exception:
            self.diagnostics_dir.mkdir(parents=True, exist_ok=True)
            editor.screenshot(
                path=str(self.diagnostics_dir / f"chapter-{chapter.number}-failure.png"),
                full_page=True,
            )
            raise
        finally:
            if editor != self.page and not editor.is_closed():
                editor.close()


def run_publish(
    *,
    runtime_path: Path,
    ledger_path: Path,
    book: str,
    state_path: Path,
    from_chapter: int | None = None,
    to_chapter: int | None = None,
    count: int | None = None,
    headless: bool = False,
    dry_run: bool = False,
    schedule: bool = False,
    chapters_per_day: int = 8,
    daily_char_limit: int | None = None,
    schedule_start_date: str | None = None,
    schedule_time: str = "01:00",
    schedule_timezone: str = "Asia/Shanghai",
) -> list[int]:
    jobs = select_jobs(
        load_jobs(ledger_path),
        from_chapter=from_chapter,
        to_chapter=to_chapter,
        count=count,
    )
    if not jobs:
        return []
    parsed = {
        job.number: parse_upload_file(
            runtime_path / job.queued_file,
            expected_action=job.expected_action,
        )
        for job in jobs
    }
    if not state_path.is_file():
        raise PublishError(f"缺少登录状态：{state_path}")
    completed = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=CHROMIUM_ARGS)
        context = browser.new_context(storage_state=str(state_path))
        publisher = FanqiePublisher(
            context=context,
            book=book,
            diagnostics_dir=runtime_path / "diagnostics",
        )
        try:
            existing_day_chars: dict[date, int] = {}
            effective_start_date = schedule_start_date
            if schedule and schedule_start_date is None:
                manager = publisher._open_chapter_manager()
                scheduled_items = publisher.inspect_scheduled_chapters(manager)
                char_counts = load_chapter_char_counts(ledger_path, runtime_path)
                existing_day_chars = summarize_existing_day_chars(
                    scheduled_items, char_counts
                )
                if scheduled_items:
                    latest_day = max(item[1] for item in scheduled_items)
                    effective_start_date = latest_day.isoformat()
                    used = existing_day_chars.get(latest_day, 0)
                    if daily_char_limit is not None and used >= daily_char_limit:
                        effective_start_date = (latest_day + timedelta(days=1)).isoformat()
                else:
                    effective_start_date = None
            plan = build_publish_plan(
                jobs,
                runtime_path=runtime_path,
                schedule=schedule,
                chapters_per_day=chapters_per_day,
                daily_char_limit=daily_char_limit,
                existing_day_chars=existing_day_chars,
                schedule_start_date=effective_start_date,
                schedule_time=schedule_time,
                timezone_name=schedule_timezone,
            )
            if dry_run:
                print_publish_plan(plan)
                return [item.job.number for item in plan]
            for item in plan:
                job = item.job
                publisher.publish(
                    parsed[job.number],
                    scheduled_at=item.scheduled_at,
                )
                processed_scheduled_at = (
                    None if publisher.last_editor_action == "edit" else item.scheduled_at
                )
                mark_processed(
                    runtime_path=runtime_path,
                    ledger_path=ledger_path,
                    job=job,
                    book=book,
                    now=now_iso(),
                    scheduled_at=processed_scheduled_at,
                )
                completed.append(job.number)
                time.sleep(1)
        finally:
            context.close()
            browser.close()
    return completed


def probe_publish_actions(
    *,
    runtime_path: Path,
    ledger_path: Path,
    book: str,
    state_path: Path,
    from_chapter: int | None = None,
    to_chapter: int | None = None,
    count: int | None = None,
    headless: bool = False,
) -> list[tuple[int, str]]:
    jobs = select_jobs(
        load_jobs(ledger_path),
        from_chapter=from_chapter,
        to_chapter=to_chapter,
        count=count,
    )
    if not jobs:
        return []
    parsed = {job.number: parse_upload_file(runtime_path / job.queued_file) for job in jobs}
    if not state_path.is_file():
        raise PublishError(f"缺少登录状态：{state_path}")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, args=CHROMIUM_ARGS)
        context = browser.new_context(storage_state=str(state_path))
        publisher = FanqiePublisher(
            context=context,
            book=book,
            diagnostics_dir=runtime_path / "diagnostics",
        )
        try:
            manager = publisher._open_chapter_manager()
            result = []
            for job in jobs:
                action = publisher.detect_chapter_action(manager, parsed[job.number])
                result.append((job.number, action))
            return result
        finally:
            context.close()
            browser.close()
