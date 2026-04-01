import { transport } from './index'
import type { ApiResponse, PaginatedResponse, Novel } from '../../types/models'

export const novelApi = {
  list: (skip = 0, limit = 100) =>
    transport.get<PaginatedResponse<Novel>>('/novels', { params: { skip, limit } }),

  get: (id: number) =>
    transport.get<ApiResponse<Novel>>(`/novels/${id}`),

  create: (data: {
    title: string
    genre?: string
    synopsis: string
    total_chapters?: number
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<Novel>>('/novels', data),

  update: (id: number, data: Partial<{
    title: string
    genre: string
    synopsis: string
    outline: string
    total_chapters: number
    ai_config_id: number | null
    system_prompt: string | null
  }>) =>
    transport.patch<ApiResponse<Novel>>(`/novels/${id}`, data),

  delete: (id: number) =>
    transport.delete<void>(`/novels/${id}`),
}
