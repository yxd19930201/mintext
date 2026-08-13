const { contextBridge, ipcRenderer } = require('electron')

const prefix = '--minitext-server-url='
const arg = process.argv.find(value => value.startsWith(prefix))
contextBridge.exposeInMainWorld('minitextDesktop', Object.freeze({
  serverUrl: arg ? arg.slice(prefix.length) : 'http://127.0.0.1:8000',
  platform: process.platform,
  webAi: Object.freeze({
    status: () => ipcRenderer.invoke('web-ai-status'),
    probe: provider => ipcRenderer.invoke('web-ai-probe', provider),
    login: provider => ipcRenderer.invoke('web-ai-login', provider),
  }),
  browserExtension: Object.freeze({
    openFolder: () => ipcRenderer.invoke('browser-extension-open-folder'),
  }),
}))
