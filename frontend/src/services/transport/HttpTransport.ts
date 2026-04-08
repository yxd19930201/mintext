import axios, { type AxiosInstance } from 'axios'
import type { ITransport, RequestOptions } from './ITransport'

export class HttpTransport implements ITransport {
  private client: AxiosInstance

  constructor(baseURL = '/api/v1') {
    this.client = axios.create({ baseURL, timeout: 600000 })

    this.client.interceptors.request.use((config) => {
      const token = localStorage.getItem('access_token')
      if (token) config.headers.Authorization = `Bearer ${token}`
      return config
    })
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
