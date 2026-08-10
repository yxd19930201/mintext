const { app, BrowserWindow, dialog, Menu, shell, nativeTheme } = require('electron')
const { spawn } = require('child_process')
const fs = require('fs')
const net = require('net')
const path = require('path')

// Keep this path stable across all future product versions and installer upgrades.
// Program files may be replaced, but user data must never live in the install folder.
const stableUserDataDir = path.join(app.getPath('appData'), 'Mintext')
app.setPath('userData', stableUserDataDir)

let serverProcess = null
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

function waitForServer(url, timeoutMs = 60000) {
  const deadline = Date.now() + timeoutMs
  return new Promise((resolve, reject) => {
    const check = async () => {
      if (serverProcess?.exitCode !== null) {
        reject(new Error(`内置服务已退出，退出码：${serverProcess.exitCode}`))
        return
      }
      try {
        const response = await fetch(`${url}/health`)
        if (response.ok) {
          resolve()
          return
        }
      } catch (_) {}
      if (Date.now() >= deadline) reject(new Error('内置服务启动超时'))
      else setTimeout(check, 300)
    }
    check()
  })
}

async function startBundledServer() {
  const override = externalServerUrl()
  if (override) return override
  if (!app.isPackaged) return 'http://127.0.0.1:8000'

  const executable = path.join(process.resourcesPath, 'server', 'mintext-server.exe')
  if (!fs.existsSync(executable)) throw new Error(`找不到内置服务：${executable}`)
  const port = await findFreePort()
  const dataDir = path.join(app.getPath('userData'), 'server-data')
  fs.mkdirSync(dataDir, { recursive: true })
  const log = fs.openSync(path.join(app.getPath('userData'), 'server.log'), 'a')
  serverProcess = spawn(executable, [
    '--host', '127.0.0.1', '--port', String(port), '--data-dir', dataDir,
  ], {
    windowsHide: true,
    stdio: ['ignore', log, log],
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
  serverProcess = null
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
    const url = await startBundledServer()
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
      startBundledServer().then(createWindow).catch(error => {
        dialog.showErrorBox('Mintext 启动失败', error.message)
      })
    }
  })
})
app.on('before-quit', stopBundledServer)
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})
