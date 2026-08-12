# mintext

小说 AI 流程已集成 `novel-continuity-writer` skill。小说大纲、章节正文、自动续写和连续性记忆更新会自动加载 skill 的阶段规则；小说或请求中配置的自定义 system prompt 会作为项目文风要求叠加，不会关闭连续性规则。

完整 skill 位于 `backend/app/skills/novel-continuity-writer/`，运行时精简适配器位于 `backend/app/services/novel_skill_service.py`。

## 一体化桌面工具

- 安装包内含 Electron 客户端和 FastAPI 服务端。
- 安装包同时内含网页版 AI 适配器；选择“免费”模式后，可复用本机 DeepSeek 或 ChatGPT 网页登录状态完成小说大纲与正文、短剧大纲与剧本、小说转短剧、短剧转分镜和 AI 助手体检，并自动回写到对应项目。
- AI 助手支持直接选择书架小说、导入单个文本或导入按章保存的文件夹；文件夹模式会按章节顺序完整送检，每批保存检查点，中断后可继续，不再以抽样片段代替长篇全文。
- 用户只需安装并启动 Mintext；程序会自动选择空闲本机端口、启动内置服务并在退出时关闭。
- 数据保存在 Electron 用户数据目录的 `server-data/minitext.db`，升级应用不会删除作品。
- 日常销售和交付只需提供 `frontend/release/Mintext Setup 0.1.0.exe`。

### 开发运行

```powershell
# 开发模式仍然分两个进程，便于调试。终端 1
cd backend
python -m uvicorn app.main:app --port 8000

# 首次运行先构建网页版适配器
cd web-ai-adapter
npm install --ignore-scripts
npm run build

# 终端 2（Electron 会自动启动网页版适配器）
cd frontend
npm install
npm run desktop:dev
```

### 构建 Windows 安装包

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build-all.ps1
```

产物：

- 最终一体化安装程序：`frontend/release/Mintext Setup 0.1.0.exe`
- `backend/dist/mintext-server.exe` 是被安装包内嵌的构建中间产物，不需要单独交付客户。

默认使用内置服务。仅在开发或企业集中部署时，可覆盖为远程服务：

```powershell
Mintext.exe --server-url=http://192.168.1.10:8000
```
