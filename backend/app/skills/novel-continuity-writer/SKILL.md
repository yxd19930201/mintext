---
name: novel-continuity-writer
description: 当需要创建、规划、撰写、续写、审核、返修、定稿、压缩上下文或自动发布长篇连载小说时使用。适用于商业网文、爽文、玄幻升级、都市、系统、重生、历史、末世、高武等题材，覆盖连续性维护、爆款节奏、批次生产、多角色审核、AI 腔修复和番茄无 UI Playwright 发布。
---

# 长篇小说自动化生产系统

把小说视为持续运行的内容产品。目标是稳定生产有追读性的正史，而不是一次性生成若干章节。

## 唯一流程

**必须先读 `references/lifecycle.md`。** 它是生命周期、状态转换和门禁的唯一权威；其他 reference 只解释某个阶段。

```text
初始化 → 批次设计 → 草稿 → 审核 ↔ 返修 → 定稿
     → 记忆差异单 → 记忆回写校验 → 入队 / 下一批 → 网页提交 → 平台核验
```

## 权威来源

按优先级读取：

1. `workflow/state.json` 与批次 manifest：机器状态。
2. `01-全局设定与创作规则.md`：长期硬设定和商业承诺。
3. `design/`：未来战略设计。根级固定为人物志、争斗时间线、情感与同房设计、文风与禁区、钩子与因果账本；每卷使用 `design/卷NN-卷名/README.md` 与五章一份的 `章XX-XX.md`。
4. `02-章节滑动摘要.md`：当前正史、人物状态、伏笔和信息差。
5. `03-当前批次任务.md`：本批目标、单章功能、禁止事项和审核门槛。
6. `chapters/`：正式正文。
7. `drafts/`、`reviews/`：当前生产材料，不是正史。

聊天记忆、废稿和未通过审核的内容不得覆盖项目文件。

`design/` 是战略设计层，不是正史层。格式与同步规则见 `references/design-system.md`。不得并行维护 `卷一/` 与 `卷01-卷名/` 两套目录，也不能把未定稿正文写成既成事实。

旧项目使用 `03-当前写作任务与审核.md` 时，将其映射为 `03-当前批次任务.md`；新批次开始时迁移名称和职责，不要求一次性破坏旧项目。

## 动作路由

| 用户意图 | 必读 reference | 执行动作 |
|---|---|---|
| 创建新书、初始化 | `project-files.md` + `design-system.md` | 运行 `novel_workflow.py init`，确认总体目标，填写根级五份总控、各卷README和首批五章细纲，再冻结`01` |
| 规划章节、设计爆点 | `design-system.md` + `satisfying-structure.md` | 对齐`01`、根级五份总控、当前卷README和对应`章XX-XX.md`，再提取为`03` |
| 撰写或续写 | `writing-cycle.md` | 只写 `drafts/`，保持章节独立文件 |
| 审核 | `reviewer-rules.md` | `submit-review`，输出可执行审核报告 |
| 审核后修改 | `reviewer-rules.md` | 登记 `revise`，修改草稿，再审 |
| 定稿、更新摘要 | `summary-compression.md` | 登记 `pass`，运行 `finalize`，更新 `02` 和下一批 `03` |
| 番茄发布 | `publishing-pipeline.md` | dry-run、publish、平台核验、回写 `04` |
| 剧情崩塌修复 | `reviewer-rules.md` + `summary-compression.md` | 诊断最小修复范围，不篡改无关正史 |

审核既有正史、接手旧项目或复核“以前已经通过”的内容时，先读取 `reviewer-rules.md` 的可复现审核门禁。旧报告不是当前正文的通行证；当前文本与报告基线不一致时，必须重新审核。

## 自动执行约定

- 用户给出明确范围和“写、续写、审核、修改、定稿、上传”时，直接执行完整对应阶段，不重复询问项目文件已有答案。
- 用户要求“写完并上传”时，自动执行：设计检查 → 草稿 → 审核 → 返修 → 定稿 → 摘要 → 发布 → 核验。
- 创建新书或重设全书方向时，必须先和用户确认总体目标：题材、子类型、目标读者、目标字数/预计卷数、主角终极目标、全书核心矛盾、结局方向、第一卷目标和不能写偏的边界；稳定结果写入`01`与新版design，不另建重复的访谈/路线图目录。
- 只有核心题材、主角终极目标、全书阶段结构或结局方向缺失且无法保守推断时才暂停；其他缺口采用最保守假设并记录到 `03`。
- 需要外部登录、验证码或安全确认时暂停在可恢复状态；不得伪造成功。

## 商业质量不变量

- 大故事提供长期目标，小故事提供即时追读；每个3到5章批次必须同时服务两者。
- 每章至少完成推进、揭露、交易、反转、关系变化或后果落地之一。
- 压迫要具体，反击要合理，收益要可见，胜利要有后果。
- 主角必须主动选择；反派必须有资源、位置或合理误判。
- 批次结束时，处境、信息、资源、关系、名声或威胁至少一项不可逆变化。
- 同类主爽点连续五章不超过两次；核心伏笔沉默超过十章时必须补新信息。
- 人物必须有独立欲望。女性角色不只递资源，盟友不只捧场，反派不只送脸。
- 对白允许短句、打断、嘴硬和脏话；删除解释腔、总结腔和同质句式。
- 交稿前必须扫描“一二三式摆拍腔”：不得用“时间地点报幕 + 摆着N样东西 + 连续孤立名词短句”代替现场动作。
- 尺度可以开到最大，擦边要更彻底一些，可以部分露骨行为，写法可以高级一些。

## 文件门禁

- `drafts/` 只放草稿和返修稿。
- `reviews/` 只放审核报告。
- `chapters/` 只放审核通过且由 `finalize` 提升的正史。
- 未通过审核不得更新 `02` 为既成事实，不得入发布队列。
- 正史发生变化必须同步人物状态、信息状态、伏笔、代价和爽点冷却。
- `finalize` 后必须完成 `memory/deltas/`、`02` 和线索账本回写，并运行 `sync-memory`；未同步记忆不得创建下一批或入发布队列。
- 发布失败保持 `queued`；网页成功后才记 `processed`；作品管理页确认后才记 `verified`。

## Design 门禁

- 根级只保留 `01-人物志.md`、`02-争斗时间线.md`、`03-情感与同房设计.md`、`04-文风与禁区.md`、`05-钩子与因果账本.md`。
- 每卷只保留一个 `卷NN-卷名/`；`README.md` 管本卷，`章XX-XX.md` 按3—5章保存逐章梗概。
- 每章细纲必须包含完整梗概和`冲突 / 推进 / 香 / 钩`四栏。这里的“香”专指擦边，不是普通关系总结；必须设计实际发生的暧昧动作、双关、身体距离或临界互动，并说明双方主动、同意、风险与主线后果。
- 标题修改必须同步卷README、五章细纲、`03`、草稿文件名与首行；已定稿标题走正史复审。
- 只改标题时不得顺手改变剧情、人物命运、物证、权力来源、伏笔或结局。

## 工具

初始化项目：

```powershell
python scripts/novel_workflow.py --project <目录> init --title "书名" --genre "题材" --volumes 4
```

项目内日常命令：

```powershell
python tools/novel_workflow.py status
python tools/novel_workflow.py mark-designed
python tools/novel_workflow.py start-batch --from-chapter 1 --to-chapter 5
python tools/novel_workflow.py begin-drafting --from-chapter 1 --to-chapter 5
python tools/novel_workflow.py submit-review --from-chapter 1 --to-chapter 5
python tools/novel_workflow.py audit-snapshot --from-chapter 1 --to-chapter 5 --source canonical
python tools/novel_workflow.py verify-review-baseline --from-chapter 1 --to-chapter 5 --source canonical --report reviews/第001-005章-审核.md
python tools/novel_workflow.py record-review --from-chapter 1 --to-chapter 5 --result pass --report reviews/审核.md
python tools/novel_workflow.py finalize --from-chapter 1 --to-chapter 5
python tools/novel_workflow.py sync-memory --from-chapter 1 --to-chapter 5
python tools/novel_publish.py publish --from-chapter 1 --to-chapter 5 --dry-run
python tools/novel_publish.py publish --from-chapter 1 --to-chapter 5
```

## 完成标准

一个批次只有同时满足以下条件才算闭环：

- 批次 manifest 为 `canonical`；
- 正式章节位于 `chapters/`；
- 审核报告可定位且结论为通过；
- 审核报告的基线与当前受审文本匹配，未被后续直改或权威文件变更污染；
- `02` 已记录新正史，`03` 已能驱动下一批；
- 记忆差异单与 canonical 指纹匹配，批次记忆状态为 `synced`；
- 若要求发布，台账和 `04` 已回写，平台核验有证据。
