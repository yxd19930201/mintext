import { transport } from './index'
import type { ApiResponse, PaginatedResponse, Project } from '../../types/models'

export const projectApi = {
  list: (skip = 0, limit = 20) =>
    transport.get<PaginatedResponse<Project>>('/projects', { params: { skip, limit } }),

  get: (id: number) =>
    transport.get<ApiResponse<Project>>(`/projects/${id}`),

  create: (data: {
    title: string
    description?: string
    genre?: string
    synopsis?: string
    total_episodes?: number
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<Project>>('/projects', data),

  update: (id: number, data: Partial<{
    title: string
    description: string
    genre: string
    synopsis: string
    outline: string
    total_episodes: number
    ai_config_id: number | null
    system_prompt: string | null
  }>) =>
    transport.patch<ApiResponse<Project>>(`/projects/${id}`, data),

  delete: (id: number) =>
    transport.delete<void>(`/projects/${id}`),
}
