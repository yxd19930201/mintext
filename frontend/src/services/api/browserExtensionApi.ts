import { transport } from './index'
import type { ApiResponse } from '../../types/models'

export interface BrowserJob {
  id: string
  kind: string
  operation: string
  status: string
  payload: Record<string, unknown>
  result: Record<string, unknown>
  error?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface BrowserExtensionStatus {
  connected: boolean
  last_seen_at?: string | null
  browser?: string | null
  extension_version?: string | null
  display_name?: string | null
}

export const browserExtensionApi = {
  listJobs: (limit = 50) =>
    transport.get<ApiResponse<BrowserJob[]>>('/browser-extension/jobs', { params: { limit } }),

  status: () => transport.get<ApiResponse<BrowserExtensionStatus>>('/browser-extension/status'),

  createJob: (operation: string, payload: Record<string, unknown> = {}) =>
    transport.post<ApiResponse<BrowserJob>>('/browser-extension/jobs', {
      operation,
      kind: 'fanqie_publish',
      payload,
    }),

  publishChapter: (data: {
    chapter_id: number
    platform_book_id: string
    overwrite?: boolean
    platform_chapter_id?: string
    scheduled_at?: string
  }) => transport.post<ApiResponse<BrowserJob>>('/browser-extension/publish-chapter', data),
}
