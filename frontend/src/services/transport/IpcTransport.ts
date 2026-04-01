/**
 * IpcTransport — C/S skeleton for Tauri / Electron.
 * TODO: replace invoke() calls with the actual IPC mechanism of your desktop framework.
 *
 * Tauri example:
 *   import { invoke } from '@tauri-apps/api/core'
 *   return invoke<T>('plugin:http|fetch', { method: 'GET', url: path, ... })
 *
 * Electron example:
 *   return window.electronAPI.ipcRenderer.invoke('http-request', { method, path, body })
 */
import type { ITransport, RequestOptions } from './ITransport'

export class IpcTransport implements ITransport {
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async get<T>(path: string, _options?: RequestOptions): Promise<T> {
    // TODO: implement via Tauri invoke / Electron ipcRenderer
    throw new Error(`IpcTransport.get not implemented for path: ${path}`)
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async post<T>(path: string, _body?: unknown, _options?: RequestOptions): Promise<T> {
    throw new Error(`IpcTransport.post not implemented for path: ${path}`)
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async patch<T>(path: string, _body?: unknown, _options?: RequestOptions): Promise<T> {
    throw new Error(`IpcTransport.patch not implemented for path: ${path}`)
  }

  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async delete<T>(path: string, _options?: RequestOptions): Promise<T> {
    throw new Error(`IpcTransport.delete not implemented for path: ${path}`)
  }
}
