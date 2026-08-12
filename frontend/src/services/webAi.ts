import type { WebAiProviderStatus } from './transport/HttpTransport'

export type FreeProvider = 'deepseek' | 'chatgpt'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`http://127.0.0.1:4310${path}`, init)
  const body = await response.json()
  if (!response.ok) throw new Error(body?.error?.message || `网页版 AI 请求失败：HTTP ${response.status}`)
  return body as T
}

export const webAi = {
  status: async (): Promise<{ providers: WebAiProviderStatus[] }> => {
    if (window.minitextDesktop?.webAi) return window.minitextDesktop.webAi.status()
    return request('/v1/providers')
  },
  probe: async (provider: FreeProvider): Promise<WebAiProviderStatus> => {
    if (window.minitextDesktop?.webAi) return window.minitextDesktop.webAi.probe(provider)
    return request(`/v1/providers/${provider}/probe`)
  },
  login: async (provider: FreeProvider): Promise<WebAiProviderStatus> => {
    if (window.minitextDesktop?.webAi) return window.minitextDesktop.webAi.login(provider)
    return request(`/v1/providers/${provider}/login`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ timeoutMs: 10 * 60_000 }),
    })
  },
}
