import axios, { type AxiosInstance } from 'axios'
import type { ITransport, RequestOptions } from './ITransport'

export class HttpTransport implements ITransport {
  private client: AxiosInstance

  constructor(baseURL = getApiBaseUrl()) {
    // A full Skill generation can include draft, strict review, up to three
    // automatic repairs and canon-ledger extraction. Let the local desktop
    // server own cancellation instead of aborting a valid long-running batch.
    this.client = axios.create({ baseURL, timeout: 0 })

    this.client.interceptors.request.use((config) => {
      const token = localStorage.getItem('access_token')
      if (token) config.headers.Authorization = `Bearer ${token}`
      return config
    })

    this.client.interceptors.response.use(
      response => response,
      error => {
        const detail = error?.response?.data?.detail
        if (typeof detail === 'string' && detail.startsWith('AI_CONFIG_REQUIRED:')) {
          const message = detail.slice('AI_CONFIG_REQUIRED:'.length)
          error.message = message
          error.response.data.detail = message
        }
        if (detail && typeof detail === 'object' && detail.message) {
          const issues = Array.isArray(detail.issues)
            ? detail.issues
                .slice(0, 5)
                .map((item: any) => item.repair_instruction || item.evidence || item.type || String(item))
                .join('；')
            : ''
          error.message = issues ? `${detail.message}：${issues}` : detail.message
        }
        return Promise.reject(error)
      },
    )
  }

  async get<T>(path: string, options?: RequestOptions): Promise<T> {
    const res = await this.client.get<T>(path, { params: options?.params, headers: options?.headers })
    return res.data
  }

  async post<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    const res = await this.client.post<T>(path, body, { params: options?.params, headers: options?.headers })
    return res.data
  }

  async patch<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
    const res = await this.client.patch<T>(path, body, { params: options?.params, headers: options?.headers })
    return res.data
  }

  async delete<T>(path: string, options?: RequestOptions): Promise<T> {
    const res = await this.client.delete<T>(path, { params: options?.params, headers: options?.headers })
    return res.data
  }
}

declare global {
  interface Window {
    minitextDesktop?: { serverUrl: string; platform: string }
  }
}

function getApiBaseUrl(): string {
  const desktopServer = window.minitextDesktop?.serverUrl
  const configuredServer = localStorage.getItem('minitext_server_url')
  const server = (configuredServer || desktopServer || import.meta.env.VITE_SERVER_URL || '').replace(/\/$/, '')
  return server ? `${server}/api/v1` : '/api/v1'
}
