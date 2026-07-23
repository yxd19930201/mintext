# 长篇小说自动化生产生命周期

本文是本 Skill 唯一的流程权威。其他 reference 只解释某个阶段，不得另建冲突流程。

## 双状态机

创作状态：

```text
initialized → designed → planned → drafting → reviewing
                              ↘ revising → reviewing
                                           ↘ approved → canonical → memory_pending → memory_synced
```

发布状态：

```text
canonical → queued → processed → verified
```

任何内容只能向右移动。返修只在 `reviewing ↔ revising` 循环；正文到达 `canonical` 后必须完成 `memory_pending → memory_synced`，才可创建下一批或发布。

## 各状态的证据

| 状态 | 权威证据 | 允许动作 |
|---|---|---|
| initialized | 四个核心文件、`design/` 初始目录、`workflow/state.json` | 总体目标访谈、全书路线设计、卷级设计 |
| designed | `01`已冻结；design根级五份总控、首卷README和首批`章XX-XX.md`已完成 | 设计首批 |
| planned | `03-当前批次任务.md`、批次 manifest | 撰写草稿 |
| drafting | `drafts/` 中独立章节草稿 | 继续写、内部自检 |
| reviewing | 草稿齐全，manifest 为 reviewing | 独立审核 |
| revising | 审核报告为需修改 | 只修改草稿 |
| approved | 审核报告为通过 | 定稿 |
| canonical | `chapters/` 正式章节，记忆回写尚待完成 | 填写记忆差异单 |
| memory_pending | 正史章节已提升，记忆差异单待回写 | 更新 `02`、账本与卷级摘要 |
| memory_synced | 差异单、账本和 `02` 已按 canonical 指纹登记 | 入发布队列、开始下一批 |
| queued | `publishing/ledger.json` 为 queued | 网页提交 |
| processed | 网页返回成功，文件已归档 | 平台核验 |
| verified | 作品管理页确认 | 更新发布状态 |

## 完整闭环

### 1. 初始化

运行：

```powershell
python <skill>/scripts/novel_workflow.py --project <目录> init --title "书名" --genre "题材" --volumes 4
```

产出全局设定、滑动摘要、当前批次任务、发布状态、`design/` 目录和机器状态。

初始化后不得直接开写。必须先站在全书层面与用户完成总体目标访谈，确认：

- 题材、子类型、平台读者和目标读感；
- 目标字数、预计章节数、预计卷数；
- 主角终极目标、初始处境、核心缺陷、成长终点；
- 全书核心矛盾、最大敌对力量和结局方向；
- 每卷大致阶段功能，至少细化第一卷；
- 每10章稳定兑现的爽点和不能写偏的边界。

访谈的稳定结果写入`01`，随后按`design-system.md`生成或补全：

- `design/01-人物志.md`；
- `design/02-争斗时间线.md`；
- `design/03-情感与同房设计.md`；
- `design/04-文风与禁区.md`；
- `design/05-钩子与因果账本.md`；
- `design/卷01-卷名/README.md`；
- `design/卷01-卷名/章01-05.md`。

每卷只保留一个`卷NN-卷名/`目录。README保存卷级设计；`章XX-XX.md`保存3—5章逐章梗概，每章固定写完整梗概及`冲突、推进、香、钩`四栏。“香”只能写真实擦边机制，不得用普通关系变化冒充。

完成全局设计后，把稳定承诺压缩进 `01-全局设定与创作规则.md`，并将创作状态视为 `designed`。只有 `designed` 之后才能设计首批。

```powershell
python tools/novel_workflow.py mark-designed
```

### 2. 设计批次

```powershell
python tools/novel_workflow.py start-batch --from-chapter 1 --to-chapter 5
```

设计批次前先读取`01`、design根级五份总控、当前卷README和对应`章XX-XX.md`。在`03`中写清：

- 大主线交付；
- 小故事诱因、阻力、结算、余波；
- 每章功能；
- 爽点轮换；
- 人物与关系变化；
- 禁止事项和审核门槛。

每个批次必须说明它服务当前卷的哪个阶段目标，以及批次结束后主角在处境、信息、资源、关系、名声或威胁上产生哪一项不可逆变化。

### 3. 创作或续写

开始写作前运行：

```powershell
python tools/novel_workflow.py begin-drafting --from-chapter 1 --to-chapter 5
```

只读取 `01`、`02`、`03`，必要时回读上一章。草稿按独立文件写入：

```text
drafts/第001章-标题.txt
```

首行必须是 `第1章 标题`。不得把未审核正文写入 `chapters/` 或 `02`。

### 4. 提交审核

```powershell
python tools/novel_workflow.py submit-review --from-chapter 1 --to-chapter 5
```

此命令验证章号连续、标题存在、正文非空。审核只基于 `01`、`02`、`03` 和本批草稿。

命令还会冻结审核基线：草稿和三份权威文件的内容摘要写入批次 manifest。审核报告必须携带命令输出的 `审核基线：sha256:...`；正文或权威文件一旦变动，本次审核立即失效。

### 5. 审核与返修

审核报告写入 `reviews/`，结论只能为：

- `pass`：所有硬门槛通过；
- `revise`：列出可定位、可执行的必改问题。

登记：

```powershell
python tools/novel_workflow.py record-review --from-chapter 1 --to-chapter 5 --result revise --report reviews/第001-005章-审核.md
```

返修只改 `drafts/`。修改后重新 `submit-review` 和 `record-review`，直至 pass。不得把上一轮“通过”复制给返修后的正文；每轮返修都必须有新基线、新报告和新结论。

### 6. 定稿

```powershell
python tools/novel_workflow.py finalize --from-chapter 1 --to-chapter 5
```

脚本只允许 approved 批次进入 `chapters/`。定稿后立即更新：

- `02`：人物、因果、信息状态、伏笔、代价、爽点冷却；
- `03`：下一批任务；
- `workflow/state.json`：最新正史章节。

脚本会保存定稿正文摘要。已经定稿的章节如需严改，必须先作为正史复审重新计算 canonical 审核基线并提交新报告；不得直接改正文后沿用旧审核结论。

### 7. 上传

```powershell
python tools/novel_publish.py publish --from-chapter 1 --to-chapter 5 --dry-run
python tools/novel_publish.py publish --from-chapter 1 --to-chapter 5
```

发布脚本只从 `chapters/` 入队。网页成功后记 processed；作品管理页确认后才记 verified。

## 自动化运行原则

- 用户给出明确章节范围和“继续/写/审核/发布”时，直接执行对应阶段，不重复询问项目文件已有答案。
- 项目文件缺少可安全推断的信息时，使用最保守假设并在 `03` 记录；只有会改变核心题材、主角目标或结局方向时才需要用户选择。
- 每次恢复工作先读机器状态，再读`01`、`02`、`03`；需要判断全书阶段或卷目标时，同时读取design根级五份总控、当前卷README和对应五章细纲。聊天历史不作为正史。
- 失败停在原状态，不伪造下一状态：审核失败不定稿，发布失败不归档，平台未核验不称已发布。
- 历史审核报告只证明其自身基线版本曾被审过。当前正文是否仍通过，必须由当前正文的审核基线验证，不以报告文件名、旧分数或聊天记忆代替。

## 爆款优化回路

每个批次都执行：

```text
读者承诺 → 压力落地 → 主角选择 → 情绪结算
        → 实际收益 → 新代价 → 下一批更强问题
```

每20章额外审计：

- 卖点是否仍在兑现；
- 主角目标是否更近；
- 敌人层级是否升级；
- 爽点是否重复；
- 人物关系是否发生不可逆变化；
- 核心伏笔是否持续有新信息；
- 是否存在可删除而不影响主线的水章。

每卷结束额外审计：

- 本卷开卷承诺是否兑现；
- 主角是否完成本卷阶段变化；
- 敌人层级是否自然升级；
- 资源、名声、关系或威胁是否出现不可逆变化；
- 下一卷引擎是否已经清楚；
- `01` 的分卷总览和 `design/下一卷/` 是否需要同步修订。
