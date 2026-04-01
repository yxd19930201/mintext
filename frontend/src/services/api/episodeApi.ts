import { transport } from './index'
import type { ApiResponse, PaginatedResponse, Episode } from '../../types/models'

export const episodeApi = {
  list: (projectId: number) =>
    transport.get<PaginatedResponse<Episode>>(`/projects/${projectId}/episodes`),

  get: (projectId: number, episodeId: number) =>
    transport.get<ApiResponse<Episode>>(`/projects/${projectId}/episodes/${episodeId}`),

  create: (projectId: number, data: { title: string; episode_number: number; synopsis?: string }) =>
    transport.post<ApiResponse<Episode>>(`/projects/${projectId}/episodes`, data),

  update: (projectId: number, episodeId: number, data: Partial<{ title: string; episode_number: number; synopsis: string }>) =>
    transport.patch<ApiResponse<Episode>>(`/projects/${projectId}/episodes/${episodeId}`, data),

  delete: (projectId: number, episodeId: number) =>
    transport.delete<void>(`/projects/${projectId}/episodes/${episodeId}`),
}
