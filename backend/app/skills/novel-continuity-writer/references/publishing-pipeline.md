# 番茄自有发布方法论

## 核心原则

发布承接 `lifecycle.md` 中的 canonical，只负责以下状态：

```text
canonical -> queued -> processed -> verified
```

- `chapters/`：唯一正史。
- `queued`：已从正史生成待发副本。
- `processed`：网页提交成功并已归档，等待平台核验。
- `verified`：作品管理页确认章号、标题或最新章节。
- 单章若因平台限制未提交成功，维持 `queued`，不得伪造为 `processed`。

不得跳过状态，也不得用聊天记忆代替 `ledger.json`。

## 项目结构

```text
novel-project/
  chapters/
  publishing/
    fanqie.json
    ledger.json
  tools/
    novel_publish.py
    fanqie_headless.py
  .runtime/
    fanqie/
      state.template.json
      state.json
      chapters/<书名>/
      uploaded/<书名>/
      diagnostics/
```

`.runtime/` 必须加入 `.gitignore`。每本书独立保存登录状态，禁止跨书复用队列。

## 初始化

完整项目由创作工作流初始化：

```powershell
python <skill>/scripts/novel_workflow.py --project <目录> init --title "书名" --genre "题材"
python tools/novel_publish.py doctor
python tools/novel_publish.py login
```

初始化不访问 Git、不下载第三方运行时。旧项目可单独运行 `novel_publish.py init` 或 `migrate` 补齐发布结构。
`state.template.json` 只提供空结构；真实登录态只写入项目自己的 `.runtime/fanqie/state.json`。

`login` 在 Windows 上默认会拉起可见浏览器，并在控制台黑框里等待。扫码或手动登录进入番茄作家后台后，必须回到黑框按一次回车，脚本才会把登录态写入项目自己的 `.runtime/fanqie/state.json`。如果只扫了码但没回车，项目仍然视为“未登录”。

## 日常命令

```powershell
# 校验正史并入队
python tools/novel_publish.py queue

# 预览本次计划
python tools/novel_publish.py publish --from-chapter 71 --to-chapter 75 --dry-run

# 默认：可见浏览器，无额外 UI
python tools/novel_publish.py publish

# 限定范围或数量
python tools/novel_publish.py publish --from-chapter 71 --to-chapter 75
python tools/novel_publish.py publish --count 5

# 番茄定时发布：一次性提交，平台按计划展示
python tools/novel_publish.py publish --from-chapter 71 --to-chapter 115 --schedule --dry-run
python tools/novel_publish.py publish --from-chapter 71 --to-chapter 115 --schedule

# 覆盖默认规则：每日字数阈值、起始日期、发布时间
python tools/novel_publish.py publish --from-chapter 71 --to-chapter 115 --schedule --schedule-daily-char-limit 20000 --schedule-time 01:00
python tools/novel_publish.py publish --from-chapter 71 --to-chapter 115 --schedule --schedule-start-date 2026-06-29

# 完全后台模式
python tools/novel_publish.py publish --headless

# 查看台账
python tools/novel_publish.py status

# 读取作品管理页并把 processed 更新为 verified
python tools/novel_publish.py verify --from-chapter 71 --to-chapter 75
```

## 正史格式

```text
文件名：第071章-城门白封.txt
第一行：第71章 城门白封
第二行起：正文
```

入队副本规范为：

```text
071 第71章 城门白封.txt
```

适配器拒绝空正文、缺标题、章号不一致和重复章号。正史在入队后变化时标记 `changed`；确认后执行：

```powershell
python tools/novel_publish.py queue --force-changed
```

`chapters/` 允许按卷分目录，例如 `chapters/卷二/第041章-标题.txt`。发布器必须递归扫描 `chapters/**/*.txt`，不得只读取顶层 `chapters/*.txt`。

## 定时发布排期

番茄存在每日提交/展示字数额度。大批量上传时不要按“立即发布”连续提交；应一次性把章节提交到番茄后台，并在发布设置弹窗里逐章打开“定时发布”，填写日期和时间后确认发布。

默认策略：

- 定时时间为北京时间 `01:00`。
- 每日字数阈值为 `20000` 字，按本地正史正文去空白后的字符数估算。
- 未显式传 `--schedule-start-date` 时，先进入番茄章节管理页，读取后台已有定时章节的最新日期。
- 若最新定时日的已排字数加上当前章不超过阈值，继续排同一天；否则排到后一天。
- 多章同一日可使用同一时间 `01:00`；平台会按章节审核/展示顺序处理。
- `--dry-run` 必须打印每章计划日期、时间和估算字数，确认无误后再真实发布。

实测通过的行为示例：

```text
第41-46章 -> 2026-06-29 01:00
第47章    -> 2026-06-30 01:00
```

这表示脚本读到 2026-06-29 是后台最新定时日，并在累计接近/超过 `20000` 字后自动切到 2026-06-30。

## 提交门禁

1. 只选择 `ledger.json` 中的 `queued` 记录。
2. 打开目标书籍的章节管理。若自动跳转失败，允许保留浏览器窗口，由人工手动进入“章节管理”页后继续。
3. 已有同章草稿则恢复编辑，否则新建章节。
4. 填写章号、标题、正文。
5. 点击“下一步”后先处理错别字提示、内容检测方式和风险检测弹窗。
6. 在发布设置弹窗中，AI 使用项必须选择“否”。若“否”未选中，“确认发布”可能无反馈。
7. 定时发布模式下打开“定时发布”开关，填写日期和时间，例如 `2026-06-29`、`01:00`。
8. 点击弹窗底部“确认发布”。
9. 观察平台成功反馈或发布设置弹窗关闭后，才归档并写入 `processed`，同时记录 `publish_mode=scheduled` 和 `scheduled_publish_at`。
10. 任一步失败立即停止，保留队列并保存诊断截图。

## 常见中断与处理

- 登录页、作者后台或作品管理页被反自动化拦截时：先执行 `login`，必要时保留浏览器窗口，人工手动进入后台或章节管理页后继续。
- 若 `login` 已打开浏览器且登录成功，但脚本仍提示缺少 `state.json`：优先检查是否已经回到黑框按回车保存登录态，再继续后续发布命令。
- 发布窗未弹成功提示时：先查看 `.runtime/fanqie/diagnostics/` 截图，再决定是否重试；没有成功证据时不得写入 `processed`。
- 若 Playwright Chromium 打开番茄出现 `ERR_CONNECTION_CLOSED` 或 `chrome-error://chromewebdata/`，优先给 Chromium 启动参数加入 `--ignore-certificate-errors` 后复测。
- 若失败截图停在发布设置弹窗且“是否使用AI”的“否”未选中，先修复 AI 选项点击逻辑；不要重复点击“确认发布”。
- 若失败截图停在“检测到错别字未修改，是否确定提交？”弹窗，先点击该弹窗的“提交”，进入发布设置后再配置定时发布。
- 单章字数超限时：当前章保留 `queued`，本轮停止该章；不要为了“清队列”强行截断正文，也不要单独伪造成功，留待下次与后续章节一起处理。
- 若“确认发布”已点击、页面停在发布设置或编辑页、且始终未观察到成功反馈：默认按“疑似字数超限 / 平台静默拦截”处理。该章维持 `queued`，本轮不再反复重试，不写入 `processed`；后续与新章节一起再次提交。

## 平台核验

`processed` 不自动等于最终可见。发布完成后读取作品管理页：

- 最新更新章号与标题；
- 总章节数；
- 目标章节是否进入章节管理。

`verify` 会读取作品管理页的最新章号和总章数，证据覆盖目标范围后把台账更新为 `verified`。随后更新 `04-发布流水线与状态.md`。无法核验时保留 `processed` 并写“已处理待平台核验”。

## 旧项目迁移

```powershell
python tools/novel_publish.py migrate
```

迁移内容：

- `state.json`
- 待发章节目录
- 已处理归档目录

迁移不删除旧目录。确认新流水线可用后，再人工清理旧 `.runtime/fanqie_auto_publish/`。
