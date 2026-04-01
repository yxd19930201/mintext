import { transport } from './index'
import type { ApiResponse, PaginatedResponse, Script } from '../../types/models'

export const scriptApi = {
  list: (episodeId: number) =>
    transport.get<PaginatedResponse<Script>>(`/episodes/${episodeId}/scripts`),

  get: (episodeId: number, scriptId: number) =>
    transport.get<ApiResponse<Script>>(`/episodes/${episodeId}/scripts/${scriptId}`),

  create: (episodeId: number, data: { content?: string; ai_prompt?: string }) =>
    transport.post<ApiResponse<Script>>(`/episodes/${episodeId}/scripts`, data),

  update: (episodeId: number, scriptId: number, data: Partial<{ content: string; ai_prompt: string; status: string }>) =>
    transport.patch<ApiResponse<Script>>(`/episodes/${episodeId}/scripts/${scriptId}`, data),

  delete: (episodeId: number, scriptId: number) =>
    transport.delete<void>(`/episodes/${episodeId}/scripts/${scriptId}`),

  generate: (episodeId: number, scriptId: number) =>
    transport.post<ApiResponse<string>>(`/episodes/${episodeId}/scripts/${scriptId}/generate`),
}
