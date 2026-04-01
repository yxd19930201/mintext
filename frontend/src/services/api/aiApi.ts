import { transport } from './index'
import type { ApiResponse, AIConfig, AIPromptPreset, OutlineResult } from '../../types/models'

export const aiApi = {
  // Configs
  listConfigs: () =>
    transport.get<ApiResponse<AIConfig[]>>('/ai/configs'),

  createConfig: (data: Omit<AIConfig, 'id' | 'created_at' | 'updated_at'>) =>
    transport.post<ApiResponse<AIConfig>>('/ai/configs', data),

  updateConfig: (id: number, data: Partial<Omit<AIConfig, 'id' | 'created_at' | 'updated_at'>>) =>
    transport.patch<ApiResponse<AIConfig>>(`/ai/configs/${id}`, data),

  deleteConfig: (id: number) =>
    transport.delete<void>(`/ai/configs/${id}`),

  // Prompt presets
  listPresets: () =>
    transport.get<ApiResponse<AIPromptPreset[]>>('/ai/prompts'),

  createPreset: (data: Omit<AIPromptPreset, 'id' | 'created_at' | 'updated_at'>) =>
    transport.post<ApiResponse<AIPromptPreset>>('/ai/prompts', data),

  updatePreset: (id: number, data: Partial<Omit<AIPromptPreset, 'id' | 'created_at' | 'updated_at'>>) =>
    transport.patch<ApiResponse<AIPromptPreset>>(`/ai/prompts/${id}`, data),

  deletePreset: (id: number) =>
    transport.delete<void>(`/ai/prompts/${id}`),

  // Generate
  generateOutline: (projectId: number, overrides?: { total_episodes?: number; ai_config_id?: number; system_prompt?: string }) =>
    transport.post<ApiResponse<OutlineResult>>('/ai/generate/outline', { project_id: projectId, ...overrides }),

  generateScript: (episodeId: number, data?: { extra_context?: string; ai_config_id?: number; system_prompt?: string }) =>
    transport.post<ApiResponse<{ episode_id: number; script_id: number; content: string }>>(`/ai/generate/script/${episodeId}`, data ?? {}),

  batchGenerate: (projectId: number, overrides?: { ai_config_id?: number; system_prompt?: string; only_missing?: boolean }) =>
    transport.post<ApiResponse<{ total: number; succeeded: number; failed: number; errors: { episode_id: number; error: string }[] }>>(
      `/ai/generate/batch/${projectId}`,
      overrides ?? {}
    ),

  generateNextEpisode: (projectId: number, overrides?: { ai_config_id?: number; system_prompt?: string }) =>
    transport.post<ApiResponse<{ episode_id: number; episode_number: number; title: string; synopsis: string; script_id: number }>>(
      `/ai/generate/next/${projectId}`,
      overrides ?? {}
    ),
}
