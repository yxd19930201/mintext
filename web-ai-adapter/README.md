# Mintext Web AI Adapter

通过本机浏览器中的已登录会话调用 DeepSeek 和 ChatGPT，向 Mintext 提供本地 HTTP 服务。

## 环境要求

- Node.js 20 或更高版本
- Microsoft Edge、Google Chrome，或 Playwright Chromium
- 可正常访问相应网站的网络环境

## 安装与构建

```powershell
npm ci
npm run typecheck
npm run build
```

默认优先复用本机 Edge，其次 Chrome。若需要 Playwright 自带 Chromium，可执行
`npx playwright install chromium`，并把 `WEB_AI_BROWSER_CHANNEL` 设置为 `bundled`。

## 首次登录

```powershell
npm run login:deepseek
npm run login:chatgpt
```

在打开的浏览器中完成登录，然后关闭整个浏览器窗口。登录状态默认保存在 `.profiles/`。

## 启动

```powershell
npm run build
npm start
```

服务默认监听 `http://127.0.0.1:4310`，可通过 `PORT` 修改。主要接口包括：

- `GET /health`
- `GET /v1/providers`
- `GET /v1/chat/models`
- `POST /v1/chat/stream`
- `POST /v1/generate`
- `POST /v1/generate/batch`

运行期参数见 [.env.example](./.env.example)。源码不会自动读取 `.env`；由 Electron、Shell
或进程管理器注入这些环境变量。

## 开发命令

- `npm run dev`：监听源码并启动服务
- `npm run typecheck`：只做严格类型检查
- `npm run diagnose:deepseek`：保存 DeepSeek 页面诊断信息
- `npm run diagnose:chatgpt`：保存 ChatGPT 页面诊断信息
- `npm run inspect:deepseek`：检查 DeepSeek 模式控件

`.profiles/` 包含登录凭据，不应提交或复制给其他人。
