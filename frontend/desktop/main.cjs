const { app, BrowserWindow, dialog, ipcMain, Menu, shell, nativeTheme } = require('electron')
const { spawn } = require('child_process')
const fs = require('fs')
const net = require('net')
const path = require('path')

// Keep this path stable across all future product versions and installer upgrades.
// Program files may be replaced, but user data must never live in the install folder.
const stableUserDataDir = path.join(app.getPath('appData'), 'Mintext')
app.setPath('userData', stableUserDataDir)

let serverProcess = null
let webAiProcess = null
let webAiUrl = null
let mainWindow = null
let quitting = false

function backupUserDatabaseBeforeUpgrade() {
  const dataDir = path.join(app.getPath('userData'), 'server-data')
  fs.mkdirSync(dataDir, { recursive: true })
  const database = path.join(dataDir, 'minitext.db')
  const marker = path.join(dataDir, '.app-version')
  const currentVersion = app.getVersion()
  let previousVersion = ''
  try { previousVersion = fs.readFileSync(marker, 'utf8').trim() } catch (_) {}

  if (fs.existsSync(database) && previousVersion !== currentVersion) {
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const backupDir = path.join(app.getPath('userData'), 'backups', `before-${currentVersion}-${timestamp}`)
    fs.mkdirSync(backupDir, { recursive: true })
    for (const suffix of ['', '-wal', '-shm']) {
      const source = `${database}${suffix}`
      if (fs.existsSync(source)) {
        fs.copyFileSync(source, path.join(backupDir, path.basename(source)))
      }
    }
  }

  fs.writeFileSync(marker, currentVersion, 'utf8')
}

function externalServerUrl() {
  const cli = process.argv.find(arg => arg.startsWith('--server-url='))
  if (cli) return cli.slice('--server-url='.length).replace(/\/$/, '')
  return process.env.MINITEXT_SERVER_URL || null
}

function findFreePort() {
  return new Promise((resolve, reject) => {
    const probe = net.createServer()
    probe.unref()
    probe.on('error', reject)
    probe.listen(0, '127.0.0.1', () => {
      const address = probe.address()
      probe.close(() => resolve(address.port))
    })
  })
}

function waitForServer(url, timeoutMs = 60000, processHandle = serverProcess, label = '内置服务') {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const check = async () => {
      if (processHandle?.exitCode !== null) {
        reject(new Error(`${label}已退出，退出码：${processHandle.exitCode}`))
        return
      }
      try {
        const response = await fetch(`${url}/health`)
        if (response.ok) {
          resolve()
          return
        }
      } catch (_) {}
      if (Date.now() >= deadline) reject(new Error(`${label}启动超时`))
      else setTimeout(check, 300)
    }
    check()
  })
}

async function startWebAiAdapter() {
  const port = app.isPackaged ? await findFreePort() : 4310
  const adapterRoot = app.isPackaged
    ? path.join(process.resourcesPath, 'web-ai-adapter')
    : path.join(__dirname, '..', '..', 'web-ai-adapter')
  const entry = path.join(adapterRoot, 'dist', 'server.js')
  if (!fs.existsSync(entry)) throw new Error(`找不到网页版 AI 适配器：${entry}`)

  const runtimeRoot = path.join(app.getPath('userData'), 'web-ai')
  fs.mkdirSync(runtimeRoot, { recursive: true })
  const log = fs.openSync(path.join(app.getPath('userData'), 'web-ai.log'), 'a')
  webAiProcess = spawn(process.execPath, [entry], {
    cwd: adapterRoot,
    windowsHide: true,
    stdio: ['ignore', log, log],
    env: {
      ...process.env,
      ELECTRON_RUN_AS_NODE: '1',
      PORT: String(port),
      WEB_AI_PROFILE_ROOT: path.join(runtimeRoot, 'profiles'),
      WEB_AI_IDEMPOTENCY_ROOT: path.join(runtimeRoot, 'idempotency'),
      WEB_AI_DIAGNOSTICS_ROOT: path.join(runtimeRoot, 'diagnostics'),
      WEB_AI_PREWARM: 'false',
      WEB_AI_HEADLESS: 'false',
    },
  })
  webAiProcess.on('error', error => {
    if (!quitting) dialog.showErrorBox('网页版 AI 服务错误', error.message)
  })
  const url = `http://127.0.0.1:${port}`
  await waitForServer(url, 60000, webAiProcess, '网页版 AI 服务')
  webAiUrl = url
  return url
}

async function startBundledServer(adapterUrl) {
  const override = externalServerUrl()
  if (override) return override
  if (!app.isPackaged) return 'http://127.0.0.1:8000'

  const executable = path.join(process.resourcesPath, 'server', 'mintext-server.exe')
  if (!fs.existsSync(executable)) throw new Error(`找不到内置服务：${executable}`)
  // The optional browser extension must be able to discover the local API
  // without reading Electron internals. Keep the loopback port stable.
  const port = 8000
  const dataDir = path.join(app.getPath('userData'), 'server-data')
  fs.mkdirSync(dataDir, { recursive: true })
  const log = fs.openSync(path.join(app.getPath('userData'), 'server.log'), 'a')
  serverProcess = spawn(executable, [
    '--host', '127.0.0.1', '--port', String(port), '--data-dir', dataDir,
  ], {
    windowsHide: true,
    stdio: ['ignore', log, log],
    env: { ...process.env, MINITEXT_WEB_AI_URL: adapterUrl },
  })
  serverProcess.on('error', error => {
    if (!quitting) dialog.showErrorBox('Mintext 服务错误', error.message)
  })
  const url = `http://127.0.0.1:${port}`
  await waitForServer(url)
  return url
}

function stopBundledServer() {
  quitting = true
  if (serverProcess && serverProcess.exitCode === null) serverProcess.kill()
  if (webAiProcess && webAiProcess.exitCode === null) webAiProcess.kill()
  serverProcess = null
  webAiProcess = null
}

function configureWebAiIpc() {
  ipcMain.removeHandler('web-ai-status')
  ipcMain.removeHandler('web-ai-probe')
  ipcMain.removeHandler('web-ai-login')
  ipcMain.handle('web-ai-status', async () => {
    const response = await fetch(`${webAiUrl}/v1/providers`)
    if (!response.ok) throw new Error(`网页版 AI 状态检查失败：HTTP ${response.status}`)
    return response.json()
  })
  ipcMain.handle('web-ai-probe', async (_event, provider) => {
    const response = await fetch(`${webAiUrl}/v1/providers/${encodeURIComponent(provider)}/probe`)
    const body = await response.json()
    if (!response.ok) throw new Error(body?.error?.message || `渠道检测失败：HTTP ${response.status}`)
    return body
  })
  ipcMain.handle('web-ai-login', async (_event, provider) => {
    const response = await fetch(`${webAiUrl}/v1/providers/${encodeURIComponent(provider)}/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ timeoutMs: 10 * 60_000 }),
    })
    const body = await response.json()
    if (!response.ok) throw new Error(body?.error?.message || `网页登录失败：HTTP ${response.status}`)
    return body
  })
}

function configureBrowserExtensionIpc() {
  ipcMain.removeHandler('browser-extension-open-folder')
  ipcMain.handle('browser-extension-open-folder', async () => {
    const extensionPath = app.isPackaged
      ? path.join(process.resourcesPath, 'browser-extension')
      : path.join(__dirname, '..', '..', 'browser-extension')
    if (!fs.existsSync(extensionPath)) throw new Error(`找不到青玉浏览器助手：${extensionPath}`)
    const error = await shell.openPath(extensionPath)
    if (error) throw new Error(error)
    return extensionPath
  })
}

function createWindow(serverUrl) {
  // Keep Windows caption buttons and native dialogs aligned with the app's
  // light frosted-glass theme. Without this, the hidden title-bar overlay
  // keeps Electron's old dark color above an otherwise light interface.
  nativeTheme.themeSource = 'light'
  Menu.setApplicationMenu(null)
  mainWindow = new BrowserWindow({
    width: 1380,
    height: 900,
    minWidth: 1024,
    minHeight: 680,
    show: false,
    backgroundColor: '#eef4fb',
    icon: path.join(process.resourcesPath, 'icon.png'),
    autoHideMenuBar: true,
    titleBarStyle: 'hidden',
    titleBarOverlay: {
      color: '#f5f8fc',
      symbolColor: '#101318',
      height: 32,
    },
    webPreferences: {
      preload: path.join(__dirname, 'preload.cjs'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      additionalArguments: [`--minitext-server-url=${serverUrl}`],
    },
  })
  const win = mainWindow
  win.on('closed', () => {
    if (mainWindow === win) mainWindow = null
  })
  win.once('ready-to-show', () => win.show())
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https://') || url.startsWith('http://')) shell.openExternal(url)
    return { action: 'deny' }
  })
  if (process.argv.includes('--dev')) win.loadURL('http://127.0.0.1:5173')
  else win.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
}

const hasLock = app.requestSingleInstanceLock()
if (!hasLock) app.quit()
app.on('second-instance', () => {
  if (!mainWindow) return
  if (mainWindow.isMinimized()) mainWindow.restore()
  mainWindow.show()
  mainWindow.focus()
})

app.whenReady().then(async () => {
  try {
    backupUserDatabaseBeforeUpgrade()
    const adapterUrl = await startWebAiAdapter()
    const url = await startBundledServer(adapterUrl)
    configureWebAiIpc()
    configureBrowserExtensionIpc()
    createWindow(url)
  } catch (error) {
    dialog.showErrorBox('Mintext 启动失败', `${error.message}\n\n日志：${path.join(app.getPath('userData'), 'server.log')}`)
    app.quit()
  }
  app.on('activate', () => {
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    } else {
      startBundledServer(webAiUrl).then(createWindow).catch(error => {
        dialog.showErrorBox('Mintext 启动失败', error.message)
      })
    }
  })
})
app.on('before-quit', stopBundledServer)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
