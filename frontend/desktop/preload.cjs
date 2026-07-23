const { contextBridge } = require('electron')

const prefix = '--minitext-server-url='
const arg = process.argv.find(value => value.startsWith(prefix))
contextBridge.exposeInMainWorld('minitextDesktop', Object.freeze({
  serverUrl: arg ? arg.slice(prefix.length) : 'http://127.0.0.1:8000',
  platform: process.platform,
}))
