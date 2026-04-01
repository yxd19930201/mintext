import { transport } from './index'
import type { ApiResponse, NovelToScriptResult, ScriptToVideoResult } from '../../types/models'

export const conversionApi = {
  novelToScript: (data: {
    novel_text: string
    target_episodes?: number
    style?: string
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<NovelToScriptResult>>('/conversion/novel-to-script', data),

  scriptToVideo: (data: {
    script_text: string
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<ScriptToVideoResult>>('/conversion/script-to-video', data),
}
