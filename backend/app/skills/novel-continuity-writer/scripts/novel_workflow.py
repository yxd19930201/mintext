#!/usr/bin/env python3
"""长篇小说从初始化、全局设计、批次创作、审核返修到定稿的状态机。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATE_RELATIVE = Path("workflow/state.json")
BATCH_DIR_RELATIVE = Path("workflow/batches")
MEMORY_DIR_RELATIVE = Path("memory")
MEMORY_DELTA_DIR_RELATIVE = MEMORY_DIR_RELATIVE / "deltas"
MEMORY_INDEX_RELATIVE = MEMORY_DIR_RELATIVE / "delta-index.json"
MEMORY_LEDGER_RELATIVE = MEMORY_DIR_RELATIVE / "伏笔与钩子账本.md"
MEMORY_VOLUME_DIR_RELATIVE = MEMORY_DIR_RELATIVE / "卷级正史摘要"
CHAPTER_PATTERN = re.compile(r"第\s*(\d+)\s*章(?:[-_\s：:]*)(.*)")
REVIEW_BASELINE_PATTERN = re.compile(r"审核基线：\s*sha256:([0-9a-f]{64})", re.IGNORECASE)
REVIEW_REPORT_MARKERS = (
    "审核基线：",
    "总评：",
    "必改问题：",
    "连续性结论：",
    "阅读体验评分：",
    "人物与关系评分：",
    "文风自然度评分：",
    "AI 腔风险：",
)


STATE_TEMPLATE = {
    "cookies": [],
    "origins": [],
}


class WorkflowError(RuntimeError):
    """创作状态或项目文件不满足当前动作。"""


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", delete=False, dir=path.parent, suffix=".tmp"
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"无法读取状态文件：{path}: {exc}") from exc


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def snapshot_paths(root: Path, paths: list[Path], *, source: str, include_context: bool) -> dict[str, Any]:
    """创建可复现审核基线；摘要仅由文件路径与字节内容决定。"""
    records = []
    for path in paths:
        if not path.is_file():
            raise WorkflowError(f"审核基线缺少文件：{path}")
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_bytes(path.read_bytes()),
            }
        )
    if include_context:
        for name in ("01-全局设定与创作规则.md", "02-章节滑动摘要.md", "03-当前批次任务.md"):
            path = root / name
            if not path.is_file():
                raise WorkflowError(f"审核基线缺少权威文件：{name}")
            records.append(
                {"path": name, "sha256": sha256_bytes(path.read_bytes())}
            )
    records.sort(key=lambda item: item["path"])
    payload = json.dumps(
        {"source": source, "files": records},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {"source": source, "files": records, "fingerprint": sha256_bytes(payload)}


def ensure_state_template(root: Path) -> None:
    path = root.parent / "state.template.json"
    if not path.exists():
        write_json_atomic(path, STATE_TEMPLATE)


def batch_key(start: int, end: int) -> str:
    if start <= 0 or end < start:
        raise WorkflowError("批次章节范围无效")
    return f"{start:03d}-{end:03d}"


def batch_path(root: Path, start: int, end: int) -> Path:
    return root / BATCH_DIR_RELATIVE / f"{batch_key(start, end)}.json"


def memory_delta_path(root: Path, start: int, end: int) -> Path:
    return root / MEMORY_DELTA_DIR_RELATIVE / f"第{start:03d}-{end:03d}章.md"


def empty_memory_index() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "batches": {}}


def _memory_ledger_template(title: str) -> str:
    return f"""# 《{title}》伏笔与钩子账本

只记录已定稿正史中的高精度线索。`01`、`02`、`03` 仅引用 ID，不复制完整条目。

## 长线伏笔（F-）

| ID | 首次出现 | 读者已知 | 知道者/误解者 | 证据与持有者 | 最后推进 | 下次窗口 | 最晚回收 | 状态 |
|---|---:|---|---|---|---:|---|---|---|

## 短期钩子（H-）

| ID | 首次出现 | 当前问题 | 证据与持有者 | 下次窗口 | 状态 |
|---|---:|---|---|---|---|

## 规则

- 长线伏笔使用 `F-001`，短期钩子使用 `H-001`；ID 不复用。
- 每条必须说明真实作用、写作限制和状态（活跃、推进、回收、失效）。
- 未通过审核的草稿不得写入本账本。
"""


def _memory_delta_template(start: int, end: int, fingerprint: str) -> str:
    return f"""# 记忆差异单：第{start}-{end}章

- 正史基线：sha256:{fingerprint}
- 状态：待回写

## 新增事实

## 状态变化

## 线索与钩子

- 新增 ID：
- 推进 ID：
- 回收/失效 ID：

## 知识差与物证

## 收益、代价与爽点冷却

## 下一批直接承接

## 回写清单

- [ ] `02-章节滑动摘要.md`
- [ ] `memory/伏笔与钩子账本.md`
- [ ] `03-当前批次任务.md`（仅在创建下一批时重建）
"""


def volume_name(index: int) -> str:
    names = ["卷一", "卷二", "卷三", "卷四", "卷五", "卷六", "卷七", "卷八", "卷九", "卷十"]
    return names[index - 1] if 1 <= index <= len(names) else f"卷{index}"


def production_volume_name(index: int, title: str = "待定") -> str:
    return f"卷{index:02d}-{title}"


def load_state(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = root / STATE_RELATIVE
    if not path.exists():
        raise WorkflowError("缺少 workflow/state.json，请先执行 init")
    return read_json(path)


def save_state(root: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now_iso()
    write_json_atomic(root / STATE_RELATIVE, state)


def load_batch(project_root: Path | str, start: int, end: int) -> dict[str, Any]:
    root = Path(project_root).resolve()
    path = batch_path(root, start, end)
    if not path.exists():
        raise WorkflowError(f"批次 {batch_key(start, end)} 尚未创建")
    return read_json(path)


def save_batch(root: Path, manifest: dict[str, Any]) -> None:
    manifest["updated_at"] = now_iso()
    write_json_atomic(
        batch_path(root, int(manifest["start"]), int(manifest["end"])), manifest
    )


def _global_template(title: str, genre: str, volumes: int) -> str:
    return f"""# 《{title}》全局设定与创作规则

## 项目定位

- 题材：{genre}
- 子类型：待根据初始化访谈确定。
- 目标平台与读者：待确定。
- 目标字数与预计章节数：待确定。
- 预计卷数：{volumes}
- 一句话卖点：待根据核心冲突填写。
- 目标读感：强冲突、强因果、强追读；爽点必须有收益和代价。
- 禁止偏离：不得偏离主角终极目标、全书核心矛盾和结局方向。

## 读者承诺

- 这本书持续给读者的核心爽感：
- 每10章必须兑现：
- 每卷必须升级：
- 读者追下一章的理由：
- 读者追完整本的理由：

## 全书总故事

- 主角初始处境：
- 主角终极目标：
- 核心缺陷或软肋：
- 全书核心矛盾：
- 最大敌对力量：
- 终局方向：
- 结局形态：

## 分卷总览

| 卷 | 章节范围 | 阶段功能 | 主角变化 | 敌人层级 | 卷末不可逆变化 | 设计目录 |
|---|---:|---|---|---|---|---|
{_volume_overview_rows(volumes)}

## 世界与硬规则

- 世界结构：
- 权力结构：
- 资源结构：
- 力量、金钱、地位增长规则：
- 限制与代价：
- 不允许临时开挂的边界：

## 核心人物与关系规则

- 人物必须有独立欲望、秘密、底线和主动选择。
- 女性角色不只递资源，盟友不只捧场，反派不只送脸。
- 重要关系必须有阶段变化：看不起、怀疑、交易、信任、暧昧、背叛、重估等。

## 势力与反派阶梯

- 当前层级敌人：
- 上层敌人：
- 幕后矛盾：
- 反派必须有资源、位置或合理误判。

## 爽点与节奏规则

- 每章至少完成推进、揭露、交易、反转、关系变化或后果落地之一。
- 每个3到5章批次必须形成一个小故事，并给大主线交付真实变化。
- 同类主爽点连续五章不超过两次。
- 核心伏笔沉默超过十章时，下一批必须给新信息。
- 批次结束时，处境、信息、资源、关系、名声或威胁至少一项不可逆变化。

## 设计索引

- 人物：`design/01-人物志.md`
- 争斗：`design/02-争斗时间线.md`
- 情感：`design/03-情感与同房设计.md`
- 文风：`design/04-文风与禁区.md`
- 因果：`design/05-钩子与因果账本.md`
- 卷级设计：`design/卷NN-卷名/README.md`与五章一份的`章XX-XX.md`。

## 安全与禁止事项

- 角色成年、自愿；不写胁迫、失去意识、药物控制或露骨性行为过程。
- 不直接仿写具体作品的独特句式、人物或专有设定。
- 不为了短期爽点破坏硬规则、人物底线或全书结局方向。
"""


def _volume_overview_rows(volumes: int) -> str:
    return "\n".join(
        f"| {volume_name(index)} | 待定 | 待定 | 待定 | 待定 | 待定 | `design/{production_volume_name(index)}/` |"
        for index in range(1, volumes + 1)
    )


def _interview_template(title: str, genre: str, volumes: int) -> str:
    return f"""# 《{title}》初始化访谈与创作决策

## 已知输入

- 书名：{title}
- 题材：{genre}
- 初始预计卷数：{volumes}

## 必须与用户确认的问题

1. 题材与子类型是什么？
2. 目标平台、目标读者和目标读感是什么？
3. 目标字数、预计章节数、预计卷数是多少？
4. 主角最终想得到什么？
5. 主角初始处境、核心缺陷和底线是什么？
6. 全书最大的长期矛盾是什么？
7. 最大敌对力量或最终压力来自哪里？
8. 结局大方向是什么：登顶、复仇、守护、改造世界、逃离系统、真相清算或其他？
9. 第一卷必须解决什么问题？
10. 读者每10章能稳定吃到什么爽点？
11. 有哪些绝对不能写偏的内容边界？

## 决策记录

- 题材与子类型：
- 目标读者：
- 目标读感：
- 目标规模：
- 主角终极目标：
- 全书核心矛盾：
- 结局方向：
- 第一卷目标：
- 稳定爽点：
- 禁止偏离：

## 待确认事项

- 
"""


def _roadmap_template(title: str, volumes: int) -> str:
    return f"""# 《{title}》全书路线图

## 全书总体目标

- 主角从哪里出发：
- 主角最终抵达哪里：
- 全书核心矛盾如何逐卷升级：
- 读者为什么愿意追完整本：

## 阶段总览

| 卷 | 章节范围 | 阶段功能 | 核心问题 | 主要敌人层级 | 卷末钩子 |
|---|---:|---|---|---|---|
{_roadmap_rows(volumes)}

## 长线推进原则

- 每卷必须让主角在资源、名声、关系、信息或威胁上产生不可逆变化。
- 每卷末必须解决一个阶段问题，同时引出更高层问题。
- 每20章审计一次卖点、目标、敌人层级、爽点重复、关系变化和伏笔信息。
"""


def _roadmap_rows(volumes: int) -> str:
    return "\n".join(
        f"| {volume_name(index)} | 待定 | 待定 | 待定 | 待定 | 待定 |"
        for index in range(1, volumes + 1)
    )


def _protagonist_template(title: str) -> str:
    return f"""# 《{title}》主角成长线

## 主角发动机

- 外在欲望：
- 内在缺口：
- 初始误判：
- 底线：
- 不能接受的失败：
- 终极目标：
- 终局蜕变：

## 分卷成长

| 卷 | 开卷状态 | 必须学会/失去 | 关键选择 | 卷末状态 |
|---|---|---|---|---|
| 卷一 | 待定 | 待定 | 待定 | 待定 |
| 卷二 | 待定 | 待定 | 待定 | 待定 |
"""


def _factions_template(title: str) -> str:
    return f"""# 《{title}》势力与反派阶梯

| 层级 | 代表人物/势力 | 拥有资源 | 打压主角的理由 | 被击败后的后果 | 引出谁 |
|---|---|---|---|---|---|
| 地方/初级 | 待定 | 待定 | 待定 | 待定 | 待定 |
| 区域/中级 | 待定 | 待定 | 待定 | 待定 | 待定 |
| 顶层/终局 | 待定 | 待定 | 待定 | 待定 | 待定 |

## 反派规则

- 反派必须有资源、位置或合理误判。
- 反派失败必须制造后果，不能只送脸。
- 敌人层级升级必须自然来自主角收益、名声或触碰的秘密。
"""


def _relationships_template(title: str) -> str:
    return f"""# 《{title}》核心人物关系线

| 人物 | 欲望 | 秘密 | 与主角初始关系 | 关系变化路线 | 不可写成 |
|---|---|---|---|---|---|
| 待定 | 待定 | 待定 | 待定 | 待定 | 工具人 |

## 关系规则

- 重要角色必须有独立目标。
- 关系变化要通过利益、误会、选择、代价和共同经历推动。
- 不把女性角色、盟友或反派写成单一功能。
"""


def _foreshadow_template(title: str) -> str:
    return f"""# 《{title}》伏笔与回收计划

| 伏笔 | 首次出现区间 | 最大沉默章数 | 新信息补给 | 回收阶段 | 回收收益 |
|---|---:|---:|---|---|---|
| 待定 | 待定 | 10 | 待定 | 待定 | 待定 |

## 伏笔规则

- 核心伏笔沉默超过十章，下一批必须补新信息。
- 伏笔回收必须带来收益、代价、关系变化或更高层问题。
- 未定稿草稿中的伏笔不能写入 `02` 为既成事实。
"""


def _volume_templates(title: str, index: int) -> dict[str, str]:
    name = volume_name(index)
    return {
        "00-本卷总纲.md": f"""# 《{title}》{name}总纲

## 本卷在全书中的作用

- 阶段功能：
- 开卷状态：
- 卷末必须抵达：
- 本卷解决的问题：
- 本卷引出的更高层问题：

## 本卷目标

- 主角要完成：
- 读者要看到：
- 世界要展开：
- 敌人要升级：
- 关系要变化：

## 卷末状态

- 主角资源：
- 主角名声：
- 人物关系：
- 未解决矛盾：
- 下一卷引擎：
""",
        "01-阶段拆分.md": f"""# 《{title}》{name}阶段拆分

| 小阶段 | 章节范围 | 冲突 | 爽点 | 结算 | 余波 |
|---|---:|---|---|---|---|
| 起势 | 待定 | 待定 | 待定 | 待定 | 待定 |
| 升级 | 待定 | 待定 | 待定 | 待定 | 待定 |
| 爆发 | 待定 | 待定 | 待定 | 待定 | 待定 |
| 卷末 | 待定 | 待定 | 待定 | 待定 | 待定 |
""",
        "02-关键人物与关系变化.md": f"""# 《{title}》{name}关键人物与关系变化

| 人物 | 开卷位置 | 本卷欲望 | 与主角关系变化 | 卷末位置 |
|---|---|---|---|---|
| 待定 | 待定 | 待定 | 待定 | 待定 |
""",
        "03-爽点与爆点设计.md": f"""# 《{title}》{name}爽点与爆点设计

## 主爽点

- 

## 副爽点

- 

## 爆点安排

| 区间 | 压迫 | 反击 | 谁看见 | 收益 | 新麻烦 |
|---|---|---|---|---|---|
| 待定 | 待定 | 待定 | 待定 | 待定 | 待定 |
""",
        "04-伏笔与卷末钩子.md": f"""# 《{title}》{name}伏笔与卷末钩子

| 伏笔/钩子 | 出现区间 | 本卷给出的信息 | 是否回收 | 引向 |
|---|---:|---|---|---|
| 待定 | 待定 | 待定 | 待定 | 待定 |
""",
    }


def _design_characters_template(title: str) -> str:
    return f"""# 《{title}》人物志

## 一、主角

- 身份、年龄与外形锚：
- 外在欲望与内在缺口：
- 底线、秘密与终极目标：
- 分卷成长：

## 二、核心人物

| 人物 | 年龄/身份 | 欲望 | 独立利益 | 与主角关系节拍 | 不可写成 |
|---|---|---|---|---|---|
| 待定 | 明确成年 | 待定 | 待定 | 待定 | 工具人 |

## 三、反派与盟友

| 人物/势力 | 资源 | 有效优势 | 失败条件 | 后续影响 |
|---|---|---|---|---|
| 待定 | 待定 | 待定 | 待定 | 待定 |
"""


def _conflict_timeline_template(title: str, volumes: int) -> str:
    return f"""# 《{title}》争斗时间线

## 一、主线战争

| 编号 | 所在卷 | 战争/事件 | 胜负标志 | 专属手段 |
|---|---|---|---|---|
| W1 | 卷一 | 待定 | 待定 | 待定 |

## 二、卷级日历与不可逆得失

| 卷 | 章节范围 | 时间钉 | 不可逆失 | 不可逆得 | 下一卷发动机 |
|---|---:|---|---|---|---|
{_roadmap_rows(volumes)}

## 三、伤势、旅行、债务、证据与权力速查

- 
"""


def _intimacy_design_template(title: str) -> str:
    return f"""# 《{title}》情感与同房设计

所有人物必须成年、清醒、自愿、能够拒绝；关系不凭空生成权力或资源。

## 一、关系主线

| 人物 | 独立欲望 | 主动方式 | 边界 | 关系阶段 | 主线收益/代价 |
|---|---|---|---|---|---|
| 待定 | 待定 | 待定 | 待定 | 待定 | 待定 |

## 二、亲密事件与动作轮换

| ID | 章区间 | 触发正事 | 主动方 | 接触/空间 | 风险/第三人 | 关系后果 |
|---|---:|---|---|---|---|---|
| S1 | 待定 | 待定 | 待定 | 待定 | 待定 | 待定 |
"""


def _style_design_template(title: str) -> str:
    return f"""# 《{title}》文风与禁区

## 一、目标读感与视角

- 

## 二、标题与章尾钩子

- 标题4—16字，具体、双义时必须章内兑现。
- 章尾使用具名动作、期限、危险或选择。

## 三、人物口吻、能力话术与证据人话

- 

## 四、亲密文风与安全边界

- 

## 五、AI腔与绝对禁写

- 
"""


def _hook_design_template(title: str) -> str:
    return f"""# 《{title}》钩子与因果账本

## 一、3—5章批次因果

| 批次 | 读者承诺 | 本批结算 | 下一批发动机 |
|---|---|---|---|
| 1—5 | 待定 | 待定 | 待定 |

## 二、长线设计ID

| ID | 首次窗口 | 读者新知 | 证据/持有人 | 下次窗口 | 最晚回收 |
|---|---:|---|---|---:|---:|
| H-01 | 待定 | 待定 | 待定 | 待定 | 待定 |

## 三、能力、权力与证据门禁

- 
"""


def _volume_readme_template(title: str, index: int) -> str:
    name = volume_name(index)
    return f"""# 《{title}》{name}｜卷名待定

| 项 | 内容 |
|---|---|
| 命题 / 主爽 | 待定 |
| 舞台 | 待定 |
| 主敌与有效资源 | 待定 |
| 不可逆失 | 待定 |
| 不可逆得 | 待定 |
| 主角位置变化 | 待定 |
| 核心关系线 | 待定 |
| 能力升级与代价 | 待定 |
| 贯穿反派收支 | 待定 |
| 卷末发动机 | 待定 |

## 对手资源与反制证据

## 核心债务、物证与权力来源

## 本卷验收

逐章细纲另建为`章XX-XX.md`；每章写完整梗概及冲突、推进、香、钩四栏。香专指实际暧昧动作、双关、身体距离、双方同意、风险与主线后果，不得用普通关系变化代替。
"""


def _summary_template(title: str) -> str:
    return f"""# 《{title}》章节滑动摘要

## 当前快照

- 当前章节：第0章，尚未开始正文。
- 当前篇章/卷：开篇筹备。
- 当前地点与时间：
- 当前直接冲突：
- 当前大主线位置：
- 下一步动作：完成全局设计，创建第1-5章批次。

## 当前有效状态

## 活跃钩子与伏笔索引

## 最近五章单章摘要

## 第6—20章批次摘要

## 历史卷级索引

## 爽点冷却与下一批直接承接
"""


def _task_template(title: str) -> str:
    return f"""# 《{title}》当前批次任务

## 批次状态

- 当前批次：未创建。
- 生命周期：initialized。
- 草稿目录：`drafts/`
- 审核目录：`reviews/`
- 正史目录：`chapters/`

## 设计前置

- 必须先完成design根级五份总控。
- 必须先完成当前`design/卷NN-卷名/README.md`。
- 必须先完成当前五章`章XX-XX.md`，每章含完整梗概及冲突、推进、香、钩四栏；香专指真实擦边机制。
- 完成后运行 `python tools/novel_workflow.py mark-designed`。

## 本批设计

- 所属卷：
- 服务的卷阶段目标：
- 大主线交付：
- 小故事：
- 主角目标：
- 主要阻力：
- 局部结算：
- 后续代价：

## 单章功能

## 必须推进

## 禁止事项

## 审核门槛

- 连续性：通过。
- 阅读体验：不低于8分。
- 文风自然度：不低于8分。
- 未通过前不得进入 `chapters/`。
"""


def _publish_status_template(title: str) -> str:
    return f"""# 发布流水线与状态

## 基本信息

- 书名：{title}
- 主发布方式：Skill 自有无 UI Playwright 发布器。
- 登录状态：未配置。

## 发布指针

- 最新已通过审核章节：第0章。
- 最新已入队章节：无。
- 最新已处理待平台核验章节：无。
- 最新平台已确认章节：无。
- 当前待发布范围：无。

## 最近一次运行

- 时间：
- 结果：
- 问题：
"""


def install_tools(root: Path) -> None:
    scripts = Path(__file__).resolve().parent
    target_dir = root / "tools"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("novel_workflow.py", "novel_publish.py", "fanqie_headless.py"):
        source = scripts / name
        target = target_dir / name
        if source.resolve() != target.resolve():
            shutil.copy2(source, target)


def detect_latest_canonical_chapter(root: Path) -> int:
    """Return the largest chapter number in the contiguous canonical prefix."""
    numbers: set[int] = set()
    chapters = root / "chapters"
    if not chapters.exists():
        return 0
    for path in chapters.glob("*.txt"):
        match = CHAPTER_PATTERN.search(path.stem)
        if match:
            numbers.add(int(match.group(1)))
    latest = 0
    while latest + 1 in numbers:
        latest += 1
    return latest


def write_if_missing(path: Path, content: str) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def initialize_project(
    project_root: Path | str, *, title: str, genre: str, volumes: int
) -> Path:
    root = Path(project_root).resolve()
    title = title.strip()
    genre = genre.strip()
    if not title or not genre:
        raise WorkflowError("书名和题材不能为空")
    if volumes <= 0:
        raise WorkflowError("预计卷数必须大于0")

    for directory in (
        "chapters",
        "drafts",
        "reviews",
        "workflow/batches",
        "memory/deltas",
        "memory/卷级正史摘要",
        "publishing",
        "tools",
        "design",
        ".runtime/fanqie/chapters",
        ".runtime/fanqie/uploaded",
        ".runtime/fanqie/diagnostics",
    ):
        (root / directory).mkdir(parents=True, exist_ok=True)

    for index in range(1, volumes + 1):
        (root / "design" / production_volume_name(index)).mkdir(
            parents=True, exist_ok=True
        )

    templates = {
        "01-全局设定与创作规则.md": _global_template(title, genre, volumes),
        "02-章节滑动摘要.md": _summary_template(title),
        "03-当前批次任务.md": _task_template(title),
        "04-发布流水线与状态.md": _publish_status_template(title),
        "design/01-人物志.md": _design_characters_template(title),
        "design/02-争斗时间线.md": _conflict_timeline_template(title, volumes),
        "design/03-情感与同房设计.md": _intimacy_design_template(title),
        "design/04-文风与禁区.md": _style_design_template(title),
        "design/05-钩子与因果账本.md": _hook_design_template(title),
    }
    for name, content in templates.items():
        write_if_missing(root / name, content)
    write_if_missing(root / MEMORY_LEDGER_RELATIVE, _memory_ledger_template(title))
    if not (root / MEMORY_INDEX_RELATIVE).exists():
        write_json_atomic(root / MEMORY_INDEX_RELATIVE, empty_memory_index())

    for index in range(1, volumes + 1):
        write_if_missing(
            root / "design" / production_volume_name(index) / "README.md",
            _volume_readme_template(title, index),
        )

    latest_canonical = detect_latest_canonical_chapter(root)
    state = {
        "version": 3,
        "title": title,
        "genre": genre,
        "volumes": volumes,
        "lifecycle": "canonical" if latest_canonical else "initialized",
        "current_batch": None,
        "latest_canonical_chapter": latest_canonical,
        "latest_memory_synced_chapter": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    state_path = root / STATE_RELATIVE
    if not state_path.exists():
        write_json_atomic(state_path, state)

    config_path = root / "publishing" / "fanqie.json"
    if not config_path.exists():
        write_json_atomic(
            config_path,
            {
                "book": title,
                "runtime": ".runtime/fanqie",
                "chapters": "chapters",
                "auto_queue": True,
            },
        )
    ledger_path = root / "publishing" / "ledger.json"
    if not ledger_path.exists():
        write_json_atomic(
            ledger_path, {"version": 1, "updated_at": None, "chapters": {}}
        )
    gitignore = root / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    for entry in (".runtime/", "__pycache__/", "*.pyc"):
        if entry not in lines:
            lines.append(entry)
    gitignore.write_text("\n".join(lines) + "\n", encoding="utf-8")
    install_tools(root)
    ensure_state_template(root)
    return root


def mark_designed(project_root: Path | str) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state = load_state(root)
    required = [
        "01-全局设定与创作规则.md",
        "design/01-人物志.md",
        "design/02-争斗时间线.md",
        "design/03-情感与同房设计.md",
        "design/04-文风与禁区.md",
        "design/05-钩子与因果账本.md",
    ]
    missing = [name for name in required if not (root / name).exists()]
    first_volumes = sorted((root / "design").glob("卷01-*"))
    if not first_volumes:
        missing.append("design/卷01-卷名/")
    else:
        first_volume = first_volumes[0]
        if not (first_volume / "README.md").is_file():
            missing.append(f"{first_volume.relative_to(root).as_posix()}/README.md")
        if not any(first_volume.glob("章*.md")):
            missing.append(f"{first_volume.relative_to(root).as_posix()}/章XX-XX.md")
    if missing:
        raise WorkflowError(f"全局设计文件不完整：{missing}")
    if state.get("lifecycle") == "initialized":
        state["lifecycle"] = "designed"
        save_state(root, state)
    return state


def start_batch(project_root: Path | str, *, start: int, end: int) -> dict[str, Any]:
    root = Path(project_root).resolve()
    state = load_state(root)
    lifecycle = state.get("lifecycle")
    if lifecycle == "initialized":
        raise WorkflowError("尚未完成全局设计。请先补全 design/ 与 01，然后运行 mark-designed")
    if state.get("current_batch"):
        current = state["current_batch"]
        current_manifest = load_batch(root, int(current["start"]), int(current["end"]))
        if current_manifest["stage"] not in ("canonical", "abandoned"):
            raise WorkflowError(
                f"批次 {batch_key(current['start'], current['end'])} 尚未闭环"
            )
        if (
            current_manifest["stage"] == "canonical"
            and current_manifest.get("memory", {}).get("status") != "synced"
        ):
            raise WorkflowError("上一批正史记忆尚未同步；请完成记忆差异单并运行 sync-memory")
    if start != int(state.get("latest_canonical_chapter", 0)) + 1:
        raise WorkflowError("新批次必须紧接最新正史章节")
    manifest = {
        "version": 1,
        "start": start,
        "end": end,
        "stage": "planned",
        "revision": 0,
        "draft_files": [],
        "review_report": None,
        "review_result": None,
        "canonical_files": [],
        "memory": {"status": "not_required"},
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    save_batch(root, manifest)
    state["lifecycle"] = "planned"
    state["current_batch"] = {"start": start, "end": end}
    save_state(root, state)
    task = root / "03-当前批次任务.md"
    task.write_text(
        f"""# 当前批次任务：第{start}-{end}章

## 批次状态

- 生命周期：planned
- 草稿：`drafts/第XXX章-标题.txt`
- 批次清单：`workflow/batches/{batch_key(start, end)}.json`

## 全局对齐

- 所属卷：
- 当前卷阶段：
- 读取的卷级设计目录：
- 本批服务的全书目标：

## 大主线交付

## 小故事闭环

- 诱因：
- 阻力：
- 局部结算：
- 余波：

## 单章功能

## 爽点轮换

## 人物与关系变化

## 必须推进

## 禁止事项

## 审核门槛

- 连续性、阅读体验、文风自然度全部通过。
- 批次结束时，处境、信息、资源、关系、名声或威胁至少一项不可逆变化。
- 未通过审核不得定稿。
""",
        encoding="utf-8",
    )
    return manifest


def begin_drafting(
    project_root: Path | str, *, start: int, end: int
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    manifest = load_batch(root, start, end)
    if manifest["stage"] != "planned":
        raise WorkflowError(f"只有 planned 批次可以开始创作：{manifest['stage']}")
    manifest["stage"] = "drafting"
    save_batch(root, manifest)
    state = load_state(root)
    state["lifecycle"] = "drafting"
    save_state(root, state)
    return manifest


def _parse_draft(path: Path) -> tuple[int, str]:
    match = CHAPTER_PATTERN.search(path.stem)
    if not match:
        raise WorkflowError(f"无法识别草稿章号：{path.name}")
    number = int(match.group(1))
    title = match.group(2).strip(" -_：:")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    first = next((line.strip() for line in lines if line.strip()), "")
    heading = CHAPTER_PATTERN.search(first)
    if not heading or int(heading.group(1)) != number:
        raise WorkflowError(f"草稿文件名与首行章号不一致：{path.name}")
    if not title:
        title = heading.group(2).strip(" -_：:")
    if not title:
        raise WorkflowError(f"草稿缺少标题：{path.name}")
    if not "\n".join(lines[1:]).strip():
        raise WorkflowError(f"草稿正文为空：{path.name}")
    return number, title


def collect_drafts(root: Path, start: int, end: int) -> list[Path]:
    found: dict[int, Path] = {}
    for path in (root / "drafts").glob("*.txt"):
        number, _ = _parse_draft(path)
        if start <= number <= end:
            if number in found:
                raise WorkflowError(f"第{number}章存在重复草稿")
            found[number] = path
    missing = [number for number in range(start, end + 1) if number not in found]
    if missing:
        raise WorkflowError(f"缺少草稿章节：{missing}")
    return [found[number] for number in range(start, end + 1)]


def collect_canonical_chapters(root: Path, start: int, end: int) -> list[Path]:
    """按章号收集正史；兼容按卷分目录保存的旧项目。"""
    found: dict[int, Path] = {}
    for path in (root / "chapters").rglob("*.txt"):
        match = CHAPTER_PATTERN.search(path.stem)
        if not match:
            continue
        number = int(match.group(1))
        if start <= number <= end:
            if number in found:
                raise WorkflowError(f"第{number}章存在重复正史文件：{found[number]} 与 {path}")
            found[number] = path
    missing = [number for number in range(start, end + 1) if number not in found]
    if missing:
        raise WorkflowError(f"缺少正史章节：{missing}")
    return [found[number] for number in range(start, end + 1)]


def build_review_snapshot(root: Path, start: int, end: int, *, source: str) -> dict[str, Any]:
    if source == "drafts":
        files = collect_drafts(root, start, end)
    elif source == "canonical":
        files = collect_canonical_chapters(root, start, end)
    else:
        raise WorkflowError(f"未知审核源：{source}")
    snapshot = snapshot_paths(root, files, source=source, include_context=True)
    snapshot.update({"start": start, "end": end, "created_at": now_iso()})
    return snapshot


def snapshot_matches(root: Path, snapshot: dict[str, Any]) -> bool:
    source = snapshot.get("source")
    start, end = int(snapshot["start"]), int(snapshot["end"])
    current = build_review_snapshot(root, start, end, source=source)
    return current["fingerprint"] == snapshot.get("fingerprint")


def canonical_snapshot_matches(root: Path, snapshot: dict[str, Any]) -> bool:
    """比较定稿正文快照；它不包含写前权威文件。"""
    start, end = int(snapshot["start"]), int(snapshot["end"])
    current = snapshot_paths(
        root,
        collect_canonical_chapters(root, start, end),
        source="canonical",
        include_context=False,
    )
    return current["fingerprint"] == snapshot.get("fingerprint")


def verify_review_report(report: Path, snapshot: dict[str, Any], result: str) -> str:
    text = report.read_text(encoding="utf-8-sig")
    missing = [marker for marker in REVIEW_REPORT_MARKERS if marker not in text]
    if missing:
        raise WorkflowError(f"审核报告缺少契约字段：{', '.join(missing)}")
    match = REVIEW_BASELINE_PATTERN.search(text)
    if not match:
        raise WorkflowError("审核报告缺少格式正确的审核基线：审核基线：sha256:<64位摘要>")
    if match.group(1).lower() != snapshot["fingerprint"]:
        raise WorkflowError("审核报告基线与提交审核时的正文或权威文件不一致；必须重新审核")
    expected = "总评：通过" if result == "pass" else "总评：需修改"
    if expected not in text:
        raise WorkflowError(f"审核报告结论必须与登记结果一致：缺少“{expected}”")
    return sha256_bytes(report.read_bytes())


def verify_report_baseline(
    root: Path, *, start: int, end: int, source: str, report: Path
) -> dict[str, Any]:
    if not report.is_file():
        raise WorkflowError(f"审核报告不存在：{report}")
    match = REVIEW_BASELINE_PATTERN.search(report.read_text(encoding="utf-8-sig"))
    if not match:
        raise WorkflowError("审核报告缺少格式正确的审核基线")
    current = build_review_snapshot(root, start, end, source=source)
    if match.group(1).lower() != current["fingerprint"]:
        raise WorkflowError(
            "当前文本或权威文件已偏离该报告审核的版本；旧通过结论失效，必须重新审核"
        )
    return current


def submit_review(project_root: Path | str, *, start: int, end: int) -> dict[str, Any]:
    root = Path(project_root).resolve()
    manifest = load_batch(root, start, end)
    if manifest["stage"] not in ("planned", "drafting", "revising"):
        raise WorkflowError(f"当前阶段不能提交审核：{manifest['stage']}")
    drafts = collect_drafts(root, start, end)
    manifest["stage"] = "reviewing"
    manifest["draft_files"] = [path.relative_to(root).as_posix() for path in drafts]
    manifest["review_snapshot"] = build_review_snapshot(
        root, start, end, source="drafts"
    )
    manifest["review_report_sha256"] = None
    save_batch(root, manifest)
    state = load_state(root)
    state["lifecycle"] = "reviewing"
    save_state(root, state)
    return manifest


def record_review(
    project_root: Path | str,
    *,
    start: int,
    end: int,
    result: str,
    report: Path,
) -> dict[str, Any]:
    root = Path(project_root).resolve()
    manifest = load_batch(root, start, end)
    report = report.resolve()
    if not report.is_file():
        raise WorkflowError(f"审核报告不存在：{report}")
    if result not in ("pass", "revise"):
        raise WorkflowError("审核结果只能是 pass 或 revise")
    if manifest["stage"] != "reviewing":
        raise WorkflowError(f"当前阶段不能登记审核：{manifest['stage']}")
    snapshot = manifest.get("review_snapshot")
    if not isinstance(snapshot, dict):
        raise WorkflowError("缺少审核基线；请重新运行 submit-review 后再登记结果")
    if not snapshot_matches(root, snapshot):
        raise WorkflowError("提交审核后正文或权威文件已变更；请重新运行 submit-review 并重新审核")
    report_sha256 = verify_review_report(report, snapshot, result)
    manifest["review_report"] = report.relative_to(root).as_posix()
    manifest["review_report_sha256"] = report_sha256
    manifest["review_result"] = result
    if result == "revise":
        manifest["stage"] = "revising"
        manifest["revision"] = int(manifest.get("revision", 0)) + 1
        lifecycle = "revising"
    else:
        manifest["stage"] = "approved"
        lifecycle = "approved"
    save_batch(root, manifest)
    state = load_state(root)
    state["lifecycle"] = lifecycle
    save_state(root, state)
    return manifest


def finalize_batch(
    project_root: Path | str, *, start: int, end: int
) -> list[Path]:
    root = Path(project_root).resolve()
    manifest = load_batch(root, start, end)
    if manifest["stage"] != "approved":
        raise WorkflowError("批次必须审核通过后才能定稿")
    snapshot = manifest.get("review_snapshot")
    if not isinstance(snapshot, dict) or not snapshot_matches(root, snapshot):
        raise WorkflowError("审核通过后草稿或权威文件已变更；必须重新提交审核")
    drafts = collect_drafts(root, start, end)
    promoted = []
    for draft in drafts:
        number, title = _parse_draft(draft)
        destination = root / "chapters" / f"第{number:03d}章-{title}.txt"
        if destination.exists() and destination.read_bytes() != draft.read_bytes():
            raise WorkflowError(f"正史章节已存在且内容不同：{destination.name}")
        if not destination.exists():
            shutil.copy2(draft, destination)
        promoted.append(destination)
    manifest["stage"] = "canonical"
    manifest["canonical_files"] = [
        path.relative_to(root).as_posix() for path in promoted
    ]
    manifest["canonical_snapshot"] = snapshot_paths(
        root, promoted, source="canonical", include_context=False
    )
    manifest["canonical_snapshot"].update({"start": start, "end": end})
    delta = memory_delta_path(root, start, end)
    delta.write_text(
        _memory_delta_template(start, end, manifest["canonical_snapshot"]["fingerprint"]),
        encoding="utf-8",
    )
    manifest["memory"] = {
        "status": "pending",
        "delta": delta.relative_to(root).as_posix(),
        "canonical_fingerprint": manifest["canonical_snapshot"]["fingerprint"],
    }
    save_batch(root, manifest)
    state = load_state(root)
    state["lifecycle"] = "memory_pending"
    state["latest_canonical_chapter"] = end
    state["current_batch"] = {"start": start, "end": end}
    save_state(root, state)
    return promoted


MEMORY_DELTA_MARKERS = (
    "正史基线：sha256:",
    "## 新增事实",
    "## 状态变化",
    "## 线索与钩子",
    "## 知识差与物证",
    "## 收益、代价与爽点冷却",
    "## 下一批直接承接",
)


def sync_memory(project_root: Path | str, *, start: int, end: int) -> dict[str, Any]:
    """确认记忆已按最终正史回写，并保存轻量可追溯索引。"""
    root = Path(project_root).resolve()
    manifest = load_batch(root, start, end)
    if manifest.get("stage") != "canonical":
        raise WorkflowError("只有已定稿的 canonical 批次可以同步记忆")
    memory = manifest.get("memory", {})
    if memory.get("status") == "synced":
        return manifest
    delta = root / str(memory.get("delta", ""))
    if not delta.is_file():
        raise WorkflowError("缺少记忆差异单；请先运行 finalize 或恢复该文件")
    canonical = manifest.get("canonical_snapshot")
    if not isinstance(canonical, dict) or not canonical_snapshot_matches(root, canonical):
        raise WorkflowError("正史章节已变更；必须先完成正史复审和定稿，再同步记忆")
    text = delta.read_text(encoding="utf-8-sig")
    missing = [marker for marker in MEMORY_DELTA_MARKERS if marker not in text]
    if missing:
        raise WorkflowError(f"记忆差异单缺少字段：{', '.join(missing)}")
    if "- 状态：已回写" not in text:
        raise WorkflowError("记忆差异单仍为待回写；完成事实对账后将状态改为“已回写”")
    match = re.search(r"正史基线：sha256:([0-9a-f]{64})", text, re.IGNORECASE)
    if not match or match.group(1).lower() != canonical["fingerprint"]:
        raise WorkflowError("记忆差异单的正史基线不匹配当前 canonical 章节")
    for required in (root / "02-章节滑动摘要.md", root / MEMORY_LEDGER_RELATIVE):
        if not required.is_file():
            raise WorkflowError(f"缺少记忆权威文件：{required.relative_to(root)}")
    index_path = root / MEMORY_INDEX_RELATIVE
    index = read_json(index_path) if index_path.exists() else empty_memory_index()
    index.setdefault("batches", {})[batch_key(start, end)] = {
        "chapters": [start, end],
        "canonical_fingerprint": canonical["fingerprint"],
        "delta": delta.relative_to(root).as_posix(),
        "delta_sha256": sha256_bytes(delta.read_bytes()),
        "summary_sha256": sha256_bytes((root / "02-章节滑动摘要.md").read_bytes()),
        "ledger_sha256": sha256_bytes((root / MEMORY_LEDGER_RELATIVE).read_bytes()),
        "synced_at": now_iso(),
    }
    index["updated_at"] = now_iso()
    write_json_atomic(index_path, index)
    memory.update({"status": "synced", "synced_at": now_iso()})
    manifest["memory"] = memory
    save_batch(root, manifest)
    state = load_state(root)
    state["lifecycle"] = "canonical"
    state["latest_memory_synced_chapter"] = max(
        int(state.get("latest_memory_synced_chapter", 0)), end
    )
    save_state(root, state)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="长篇小说创作闭环状态机")
    parser.add_argument("--project", default=".")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init")
    init.add_argument("--title", required=True)
    init.add_argument("--genre", required=True)
    init.add_argument("--volumes", type=int, default=4)

    commands.add_parser("mark-designed")

    start = commands.add_parser("start-batch")
    start.add_argument("--from-chapter", type=int, required=True)
    start.add_argument("--to-chapter", type=int, required=True)

    drafting = commands.add_parser("begin-drafting")
    drafting.add_argument("--from-chapter", type=int, required=True)
    drafting.add_argument("--to-chapter", type=int, required=True)

    submit = commands.add_parser("submit-review")
    submit.add_argument("--from-chapter", type=int, required=True)
    submit.add_argument("--to-chapter", type=int, required=True)

    snapshot = commands.add_parser("audit-snapshot")
    snapshot.add_argument("--from-chapter", type=int, required=True)
    snapshot.add_argument("--to-chapter", type=int, required=True)
    snapshot.add_argument("--source", choices=("drafts", "canonical"), required=True)

    verify = commands.add_parser("verify-review-baseline")
    verify.add_argument("--from-chapter", type=int, required=True)
    verify.add_argument("--to-chapter", type=int, required=True)
    verify.add_argument("--source", choices=("drafts", "canonical"), required=True)
    verify.add_argument("--report", type=Path, required=True)

    review = commands.add_parser("record-review")
    review.add_argument("--from-chapter", type=int, required=True)
    review.add_argument("--to-chapter", type=int, required=True)
    review.add_argument("--result", choices=("pass", "revise"), required=True)
    review.add_argument("--report", type=Path, required=True)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--from-chapter", type=int, required=True)
    finalize.add_argument("--to-chapter", type=int, required=True)

    memory = commands.add_parser("sync-memory", help="校验并登记 canonical 后的记忆回写")
    memory.add_argument("--from-chapter", type=int, required=True)
    memory.add_argument("--to-chapter", type=int, required=True)

    commands.add_parser("status")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.project).resolve()
    try:
        if args.command == "init":
            initialize_project(
                root, title=args.title, genre=args.genre, volumes=args.volumes
            )
            print(f"小说项目初始化完成：{root}")
        elif args.command == "mark-designed":
            mark_designed(root)
            print("全局设计已标记完成，可以创建首批")
        elif args.command == "start-batch":
            start_batch(root, start=args.from_chapter, end=args.to_chapter)
            print(f"批次已创建：{batch_key(args.from_chapter, args.to_chapter)}")
        elif args.command == "begin-drafting":
            begin_drafting(root, start=args.from_chapter, end=args.to_chapter)
            print("批次已进入 drafting")
        elif args.command == "submit-review":
            manifest = submit_review(root, start=args.from_chapter, end=args.to_chapter)
            print(
                "批次已进入 reviewing；审核报告必须写入："
                f"审核基线：sha256:{manifest['review_snapshot']['fingerprint']}"
            )
        elif args.command == "audit-snapshot":
            snapshot = build_review_snapshot(
                root,
                args.from_chapter,
                args.to_chapter,
                source=args.source,
            )
            print(f"审核基线：sha256:{snapshot['fingerprint']}")
            print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        elif args.command == "verify-review-baseline":
            snapshot = verify_report_baseline(
                root,
                start=args.from_chapter,
                end=args.to_chapter,
                source=args.source,
                report=args.report.resolve(),
            )
            print(f"审核基线匹配：sha256:{snapshot['fingerprint']}")
        elif args.command == "record-review":
            record_review(
                root,
                start=args.from_chapter,
                end=args.to_chapter,
                result=args.result,
                report=args.report,
            )
            print(f"审核结果已登记：{args.result}")
        elif args.command == "finalize":
            files = finalize_batch(root, start=args.from_chapter, end=args.to_chapter)
            print(f"已定稿 {len(files)} 章；请完成记忆差异单并运行 sync-memory")
        elif args.command == "sync-memory":
            sync_memory(root, start=args.from_chapter, end=args.to_chapter)
            print("正史记忆已同步，可创建下一批或进入发布队列")
        elif args.command == "status":
            state = load_state(root)
            print(json.dumps(state, ensure_ascii=False, indent=2))
        return 0
    except WorkflowError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
