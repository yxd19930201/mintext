#!/usr/bin/env python3
"""长篇小说项目的番茄发布单一入口。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from fanqie_headless import (
    PublishError,
    inspect_platform,
    login,
    mark_verified,
    probe_publish_actions,
    run_publish,
)


CONFIG_RELATIVE = Path("publishing/fanqie.json")
LEDGER_RELATIVE = Path("publishing/ledger.json")
WORKFLOW_BATCH_DIR_RELATIVE = Path("workflow/batches")
RUNTIME_RELATIVE = Path(".runtime/fanqie")
LEGACY_RUNTIME_RELATIVE = Path(".runtime/fanqie_auto_publish")
STATE_TEMPLATE_RELATIVE = Path("state.template.json")
CHAPTER_PATTERN = re.compile(r"第\s*(\d+)\s*章(?:[-_\s：:]*)?(.*)")
LEADING_NUMBER_PATTERN = re.compile(r"^\s*(\d+)(?:[-_\s]+)(.*)")


class ProjectError(RuntimeError):
    """用户可修复的项目或发布配置错误。"""


@dataclass(frozen=True)
class Config:
    project_root: Path
    book: str
    runtime: str = RUNTIME_RELATIVE.as_posix()
    chapters: str = "chapters"
    auto_queue: bool = True
    schedule_chapters_per_day: int = 8
    schedule_time: str = "01:00"
    schedule_timezone: str = "Asia/Shanghai"
    schedule_daily_char_limit: int = 20000

    @property
    def runtime_path(self) -> Path:
        return self.project_root / self.runtime

    @property
    def chapters_path(self) -> Path:
        return self.project_root / self.chapters

    @property
    def queue_path(self) -> Path:
        return self.runtime_path / "chapters" / self.book

    @property
    def archive_path(self) -> Path:
        return self.runtime_path / "uploaded" / self.book

    @property
    def state_path(self) -> Path:
        """Project-local auth state captured by the Fanqie login flow."""
        return self.runtime_path / "state.json"

    @property
    def state_template_path(self) -> Path:
        return self.runtime_path / "state.template.json"

    @classmethod
    def load(cls, project_root: Path | str) -> "Config":
        root = Path(project_root).resolve()
        path = root / CONFIG_RELATIVE
        if not path.exists():
            raise ProjectError(f"缺少配置文件：{path}，请先执行 init")
        data = read_json(path)
        return cls(
            project_root=root,
            book=str(data["book"]).strip(),
            runtime=data.get("runtime", RUNTIME_RELATIVE.as_posix()),
            chapters=data.get("chapters", "chapters"),
            auto_queue=bool(data.get("auto_queue", True)),
            schedule_chapters_per_day=int(data.get("schedule_chapters_per_day", 8)),
            schedule_time=str(data.get("schedule_time", "01:00")),
            schedule_timezone=str(data.get("schedule_timezone", "Asia/Shanghai")),
            schedule_daily_char_limit=int(data.get("schedule_daily_char_limit", 20000)),
        )


@dataclass(frozen=True)
class Chapter:
    number: int
    title: str
    body: str
    source: Path
    sha256: str

    @property
    def upload_name(self) -> str:
        return f"{self.number:03d} 第{self.number}章 {self.title}.txt"

    @property
    def upload_text(self) -> str:
        return f"第{self.number}章 {self.title}\n{self.body.rstrip()}\n"


@dataclass(frozen=True)
class QueueResult:
    queued: list[Path]
    unchanged: list[Path]
    changed: list[Path]


@dataclass(frozen=True)
class Check:
    code: str
    ok: bool
    message: str


STATE_TEMPLATE: dict[str, Any] = {
    "cookies": [],
    "origins": [],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectError(f"无法读取 JSON：{path}: {exc}") from exc


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    temporary.replace(path)


def ensure_state_template(auth_dir: Path) -> Path:
    template_path = auth_dir / "state.template.json"
    if not template_path.exists():
        write_json_atomic(template_path, STATE_TEMPLATE)
    return template_path


def parse_title(value: str) -> tuple[int | None, str]:
    match = CHAPTER_PATTERN.search(value)
    if match:
        return int(match.group(1)), match.group(2).strip(" -_：:")
    match = LEADING_NUMBER_PATTERN.search(value)
    if match:
        return int(match.group(1)), match.group(2).strip(" -_：:")
    return None, ""


def parse_chapter(path: Path) -> Chapter:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ProjectError(f"无法读取章节：{path}: {exc}") from exc
    lines = text.splitlines()
    first = next((index for index, line in enumerate(lines) if line.strip()), None)
    file_number, file_title = parse_title(path.stem)
    heading_number = None
    heading_title = ""
    if first is not None:
        heading_number, heading_title = parse_title(lines[first].strip())
    number = file_number if file_number is not None else heading_number
    if number is None:
        raise ProjectError(f"无法识别章节号：{path.name}")
    if file_number is not None and heading_number is not None and file_number != heading_number:
        raise ProjectError(
            f"文件名与首行章节号不一致：{path.name}（{file_number} != {heading_number}）"
        )
    title = file_title or heading_title
    if not title:
        raise ProjectError(f"缺少章节标题：{path.name}")
    title = re.sub(r'[<>:"/\\|?*]', " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    body_lines = lines[first + 1 :] if first is not None and heading_number else lines
    body = "\n".join(body_lines).strip()
    if not body:
        raise ProjectError(f"章节正文为空：{path.name}")
    normalized = f"第{number}章 {title}\n{body.rstrip()}\n"
    return Chapter(
        number=number,
        title=title,
        body=body,
        source=path,
        sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    )


def empty_ledger() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "chapters": {}}


def load_ledger(root: Path) -> dict[str, Any]:
    path = root / LEDGER_RELATIVE
    if not path.exists():
        return empty_ledger()
    data = read_json(path)
    data.setdefault("version", 1)
    data.setdefault("chapters", {})
    return data


def save_ledger(root: Path, ledger: dict[str, Any]) -> None:
    ledger["updated_at"] = now_iso()
    write_json_atomic(root / LEDGER_RELATIVE, ledger)


def discover_chapters(config: Config) -> list[Chapter]:
    if not config.chapters_path.is_dir():
        raise ProjectError(f"正史目录不存在：{config.chapters_path}")
    chapters = [parse_chapter(path) for path in config.chapters_path.rglob("*.txt")]
    seen = {}
    seen_titles = {}
    for chapter in chapters:
        if chapter.number in seen:
            raise ProjectError(
                f"重复章节号 {chapter.number}：{seen[chapter.number].name} / "
                f"{chapter.source.name}"
            )
        seen[chapter.number] = chapter.source
        title_key = re.sub(r"\s+", "", chapter.title)
        if title_key in seen_titles:
            previous = seen_titles[title_key]
            raise ProjectError(
                f"重复章节标题《{chapter.title}》：第{previous.number}章 "
                f"{previous.source.name} / 第{chapter.number}章 {chapter.source.name}"
            )
        seen_titles[title_key] = chapter
    return sorted(chapters, key=lambda item: item.number)


def ensure_memory_synced(root: Path, chapters: list[Chapter]) -> None:
    """发布只接受已完成 canonical 记忆回写的章节。"""
    if not chapters:
        return
    manifests = []
    batch_dir = root / WORKFLOW_BATCH_DIR_RELATIVE
    if batch_dir.is_dir():
        for path in batch_dir.glob("*.json"):
            data = read_json(path)
            if data.get("stage") == "canonical":
                manifests.append(data)
    for chapter in chapters:
        matching = [
            item for item in manifests
            if int(item.get("start", 0)) <= chapter.number <= int(item.get("end", -1))
        ]
        if not matching:
            raise ProjectError(f"第{chapter.number}章缺少 canonical 批次记录，不能入发布队列")
        if any(item.get("memory", {}).get("status") != "synced" for item in matching):
            raise ProjectError(f"第{chapter.number}章的正史记忆尚未同步，不能入发布队列")


def queue_chapters(
    project_root: Path | str, config: Config, *, force_changed: bool = False
) -> QueueResult:
    root = Path(project_root).resolve()
    chapters = discover_chapters(config)
    ensure_memory_synced(root, chapters)
    ledger = load_ledger(root)
    queued, unchanged, changed = [], [], []
    config.queue_path.mkdir(parents=True, exist_ok=True)
    for chapter in chapters:
        key = str(chapter.number)
        previous = ledger["chapters"].get(key)
        destination = config.queue_path / chapter.upload_name
        if previous and previous.get("sha256") == chapter.sha256:
            unchanged.append(destination)
            continue
        if previous and previous.get("sha256") != chapter.sha256 and not force_changed:
            previous.update(
                {
                    "source": chapter.source.relative_to(root).as_posix(),
                    "current_sha256": chapter.sha256,
                    "status": "changed",
                    "changed_at": now_iso(),
                }
            )
            changed.append(chapter.source)
            continue
        if previous and previous.get("queued_file"):
            old = config.runtime_path / previous["queued_file"]
            if old != destination and old.exists():
                old.unlink()
        expected_action = None
        if previous and (
            previous.get("status") in ("processed", "verified")
            or previous.get("archive_file")
        ):
            expected_action = "edit"
        write_text_atomic(destination, chapter.upload_text)
        record = {
            "number": chapter.number,
            "title": chapter.title,
            "source": chapter.source.relative_to(root).as_posix(),
            "sha256": chapter.sha256,
            "queued_file": destination.relative_to(config.runtime_path).as_posix(),
            "status": "queued",
            "queued_at": now_iso(),
        }
        if expected_action:
            record["expected_action"] = expected_action
        ledger["chapters"][key] = record
        queued.append(destination)
    save_ledger(root, ledger)
    return QueueResult(queued, unchanged, changed)


def ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    for entry in (".runtime/", "__pycache__/", "*.pyc"):
        if entry not in lines:
            lines.append(entry)
    path.write_text("\n".join(line for line in lines if line) + "\n", encoding="utf-8")


def ensure_status_file(root: Path, book: str) -> None:
    path = root / "04-发布流水线与状态.md"
    if path.exists():
        return
    path.write_text(
        "# 发布流水线与状态\n\n"
        "## 基本信息\n"
        f"- 书名：{book}\n"
        "- 主发布方式：Skill 自有无 UI Playwright 发布器\n"
        "- 登录状态：未配置\n\n"
        "## 发布指针\n"
        "- 最新已通过审核章节：\n"
        "- 最新已入队章节：\n"
        "- 最新已处理待平台核验章节：\n"
        "- 当前待发布范围：\n\n"
        "## 最近一次运行\n"
        "- 时间：\n"
        "- 结果：\n"
        "- 问题：\n",
        encoding="utf-8",
    )


def install_tools(root: Path) -> None:
    scripts = Path(__file__).resolve().parent
    destination = root / "tools"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("novel_publish.py", "fanqie_headless.py"):
        source = scripts / name
        target = destination / name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)


def migrate_legacy_runtime(root: Path, runtime: Path) -> None:
    legacy = root / LEGACY_RUNTIME_RELATIVE
    runtime.mkdir(parents=True, exist_ok=True)
    legacy_queue = legacy / "chapters"
    legacy_uploaded = legacy / "uploaded"
    for source, destination in (
        (legacy_queue, runtime / "chapters"),
        (legacy_uploaded, runtime / "uploaded"),
    ):
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)


def init_project(project_root: Path | str, book: str) -> Config:
    root = Path(project_root).resolve()
    book = book.strip()
    if not book:
        raise ProjectError("书名不能为空")
    for directory in ("chapters", "drafts", "reviews", "publishing", "tools"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    config_path = root / CONFIG_RELATIVE
    config_data = {
        "book": book,
        "runtime": RUNTIME_RELATIVE.as_posix(),
        "chapters": "chapters",
        "auto_queue": True,
        "schedule_chapters_per_day": 8,
        "schedule_time": "01:00",
        "schedule_timezone": "Asia/Shanghai",
        "schedule_daily_char_limit": 20000,
    }
    if config_path.exists():
        current = read_json(config_path)
        current.pop("repository", None)
        current["runtime"] = RUNTIME_RELATIVE.as_posix()
        current.setdefault("book", book)
        current.setdefault("chapters", "chapters")
        current.setdefault("auto_queue", True)
        current.setdefault("schedule_chapters_per_day", 8)
        current.setdefault("schedule_time", "01:00")
        current.setdefault("schedule_timezone", "Asia/Shanghai")
        current.setdefault("schedule_daily_char_limit", 20000)
        config_data = current
    write_json_atomic(config_path, config_data)
    ledger_path = root / LEDGER_RELATIVE
    if not ledger_path.exists():
        write_json_atomic(ledger_path, empty_ledger())
    ensure_gitignore(root)
    ensure_status_file(root, book)
    install_tools(root)
    config = Config.load(root)
    migrate_legacy_runtime(root, config.runtime_path)
    ensure_state_template(config.state_path.parent)
    for directory in (
        config.queue_path,
        config.archive_path,
        config.runtime_path / "diagnostics",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    return config


def doctor(project_root: Path | str) -> list[Check]:
    root = Path(project_root).resolve()
    try:
        config = Config.load(root)
    except ProjectError as exc:
        return [Check("config", False, str(exc))]
    checks = [Check("config", True, f"配置有效：{config.book}")]
    try:
        import playwright  # noqa: F401

        playwright_ok = True
    except ImportError:
        playwright_ok = False
    checks.append(
        Check(
            "playwright",
            playwright_ok,
            "Playwright 可用" if playwright_ok else "缺少 playwright，请先安装",
        )
    )
    tools_ok = all(
        (root / "tools" / name).is_file()
        for name in ("novel_publish.py", "fanqie_headless.py")
    )
    checks.append(
        Check("tools", tools_ok, "自有发布脚本可用" if tools_ok else "缺少自有发布脚本")
    )
    state_ok = config.state_path.is_file()
    checks.append(
        Check("login", state_ok, "登录状态可用" if state_ok else "缺少 state.json，请执行 login")
    )
    checks.append(Check("chapters", config.chapters_path.is_dir(), f"正史目录：{config.chapters_path}"))
    return checks


def status_summary(root: Path) -> dict[str, Any]:
    config = Config.load(root)
    ledger = load_ledger(root)
    counts = {}
    for record in ledger["chapters"].values():
        status = record.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return {"book": config.book, "counts": counts, "checks": doctor(root)}


def print_checks(checks: list[Check]) -> None:
    for check in checks:
        print(f"[{'OK' if check.ok else 'FAIL'}] {check.code}: {check.message}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="小说项目番茄发布统一入口")
    parser.add_argument("--project", default=".", help="小说项目目录")
    subparsers = parser.add_subparsers(dest="command", required=True)
    init_parser = subparsers.add_parser("init", help="初始化自有发布流水线")
    init_parser.add_argument("--book", required=True, help="番茄后台中的准确书名")
    queue_parser = subparsers.add_parser("queue", help="校验正史并生成待发队列")
    queue_parser.add_argument("--force-changed", action="store_true")
    subparsers.add_parser("doctor", help="检查发布环境")
    subparsers.add_parser("login", help="打开浏览器并保存登录状态")
    publish_parser = subparsers.add_parser("publish", help="无 UI 直接发布")
    publish_parser.add_argument("--from-chapter", type=int)
    publish_parser.add_argument("--to-chapter", type=int)
    publish_parser.add_argument("--count", type=int)
    publish_parser.add_argument("--headless", action="store_true")
    publish_parser.add_argument("--dry-run", action="store_true")
    publish_parser.add_argument(
        "--probe-actions",
        action="store_true",
        help="打开真实章节管理页，只检测每章会走修改(edit)还是新建(new)，不提交",
    )
    publish_parser.add_argument("--schedule", action="store_true", help="使用番茄定时发布")
    publish_parser.add_argument(
        "--chapters-per-day",
        type=int,
        help="定时发布每天安排的章节数，默认读取配置，初始为 8",
    )
    publish_parser.add_argument(
        "--schedule-start-date",
        help="定时发布起始日期，格式 YYYY-MM-DD，默认今天",
    )
    publish_parser.add_argument(
        "--schedule-time",
        help="每天定时发布时间，格式 HH:MM，默认读取配置，初始为 01:00",
    )
    publish_parser.add_argument(
        "--schedule-timezone",
        help="定时发布时区，默认读取配置，初始为 Asia/Shanghai",
    )
    publish_parser.add_argument(
        "--schedule-daily-char-limit",
        type=int,
        help="定时发布每日字数阈值，默认读取配置，初始为 20000",
    )
    subparsers.add_parser("status", help="显示发布台账")
    verify_parser = subparsers.add_parser("verify", help="读取作品管理页并核验发布")
    verify_parser.add_argument("--from-chapter", type=int)
    verify_parser.add_argument("--to-chapter", type=int)
    verify_parser.add_argument("--headless", action="store_true")
    subparsers.add_parser("migrate", help="迁移旧 fanqie_auto_publish 状态")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project).resolve()
    try:
        if args.command == "init":
            config = init_project(root, args.book)
            print(f"初始化完成：{config.project_root}")
            return 0
        config = Config.load(root)
        if args.command == "doctor":
            checks = doctor(root)
            print_checks(checks)
            return 0 if all(item.ok for item in checks) else 1
        if args.command == "queue":
            result = queue_chapters(root, config, force_changed=args.force_changed)
            print(
                f"新入队 {len(result.queued)}，未变化 {len(result.unchanged)}，"
                f"正文变化待确认 {len(result.changed)}"
            )
            return 2 if result.changed else 0
        if args.command == "login":
            login(config.state_path)
            return 0
        if args.command == "publish":
            result = queue_chapters(root, config)
            if result.changed:
                raise ProjectError("存在正文变化章节；确认后执行 queue --force-changed")
            checks = doctor(root)
            print_checks(checks)
            if not all(item.ok for item in checks):
                raise ProjectError("发布环境检查未通过")
            if args.probe_actions:
                actions = probe_publish_actions(
                    runtime_path=config.runtime_path,
                    ledger_path=root / LEDGER_RELATIVE,
                    book=config.book,
                    state_path=config.state_path,
                    from_chapter=args.from_chapter,
                    to_chapter=args.to_chapter,
                    count=args.count,
                    headless=args.headless,
                )
                for number, action in actions:
                    print(f"第{number}章：{'修改' if action == 'edit' else '新建'}")
                summary = {}
                for _, action in actions:
                    summary[action] = summary.get(action, 0) + 1
                print(
                    "探测结果："
                    f"修改 {summary.get('edit', 0)}，"
                    f"新建 {summary.get('new', 0)}"
                )
                return 0
            completed = run_publish(
                runtime_path=config.runtime_path,
                ledger_path=root / LEDGER_RELATIVE,
                book=config.book,
                state_path=config.state_path,
                from_chapter=args.from_chapter,
                to_chapter=args.to_chapter,
                count=args.count,
                headless=args.headless,
                dry_run=args.dry_run,
                schedule=args.schedule,
                chapters_per_day=args.chapters_per_day
                if args.chapters_per_day is not None
                else config.schedule_chapters_per_day,
                daily_char_limit=args.schedule_daily_char_limit
                if args.schedule_daily_char_limit is not None
                else config.schedule_daily_char_limit,
                schedule_start_date=args.schedule_start_date,
                schedule_time=args.schedule_time or config.schedule_time,
                schedule_timezone=args.schedule_timezone or config.schedule_timezone,
            )
            label = "计划章节" if args.dry_run else "已处理待平台核验"
            print(f"{label}：{', '.join(map(str, completed)) or '无'}")
            return 0
        if args.command == "status":
            summary = status_summary(root)
            print(f"书名：{summary['book']}")
            for status, count in sorted(summary["counts"].items()):
                print(f"{status}: {count}")
            print_checks(summary["checks"])
            return 0
        if args.command == "verify":
            ledger = load_ledger(root)
            processed = sorted(
                int(number)
                for number, record in ledger["chapters"].items()
                if record.get("status") in ("processed", "verified")
            )
            if not processed:
                raise ProjectError("没有 processed 章节可核验")
            start = args.from_chapter if args.from_chapter is not None else min(processed)
            end = args.to_chapter if args.to_chapter is not None else max(processed)
            latest, total, _ = inspect_platform(
                state_path=config.state_path,
                book=config.book,
                headless=args.headless,
            )
            verified = mark_verified(
                ledger_path=root / LEDGER_RELATIVE,
                from_chapter=start,
                to_chapter=end,
                platform_latest=latest,
                platform_total=total,
                now=now_iso(),
            )
            print(
                f"平台已确认：{', '.join(map(str, verified))}；"
                f"最新第{latest}章，共{total}章"
            )
            return 0
        if args.command == "migrate":
            migrate_legacy_runtime(root, config.runtime_path)
            print("旧发布状态迁移完成")
            return 0
    except (ProjectError, PublishError, ValueError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
