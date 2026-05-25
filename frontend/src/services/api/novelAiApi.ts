import { transport } from './index'
import type { ApiResponse, NovelOutlineResult } from '../../types/models'

export interface GenerateChapterResult {
  chapter_id: number
  content_id: number
  content: string
  word_count: number
}

export interface BatchGenerateResult {
  total: number
  succeeded: number
  failed: number
  errors: Array<{
    chapter_id: number
    chapter_number: number
    error: string
  }>
}

export interface GenerateNextChapterResult {
  chapter_id: number
  chapter_number: number
  title: string
  synopsis: string
  content_id: number
}

export interface KnowledgeGraphCharacter {
  name: string
  role: string
  description: string
  relations: Array<{ target: string; relation: string }>
}

export interface KnowledgeGraphEvent {
  chapter: number
  title: string
  description: string
  related_characters: string[]
}

export interface KnowledgeGraph {
  characters: KnowledgeGraphCharacter[]
  events: KnowledgeGraphEvent[]
}

export const novelAiApi = {
  generateOutline: (data: {
    novel_id: number
    total_chapters: number
    start_chapter?: number
    end_chapter?: number
    theme?: string
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<NovelOutlineResult>>('/novel-ai/generate/outline', data),

  generateChapter: (chapterId: number, data: {
    extra_context?: string
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<GenerateChapterResult>>(`/novel-ai/generate/chapter/${chapterId}`, data),

  batchGenerate: (novelId: number, data: {
    only_missing?: boolean
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<BatchGenerateResult>>(`/novel-ai/generate/batch/${novelId}`, data),

  generateNext: (novelId: number, data: {
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<GenerateNextChapterResult>>(`/novel-ai/generate/next/${novelId}`, data),

  getChaptersWithContent: (novelId: number) =>
    transport.get<ApiResponse<Array<{ id: number; chapter_number: number; title: string }>>>(`/novel-ai/graph/${novelId}/chapters`),

  clearGraph: (novelId: number) =>
    transport.post<ApiResponse<KnowledgeGraph>>(`/novel-ai/graph/${novelId}/clear`),

  updateGraphFromChapter: (novelId: number, chapterId: number) =>
    transport.post<ApiResponse<KnowledgeGraph>>(`/novel-ai/graph/update-chapter/${novelId}/${chapterId}`),

  getGraph: (novelId: number) =>
    transport.get<ApiResponse<KnowledgeGraph>>(`/novel-ai/graph/${novelId}`),

  rebuildGraph: (novelId: number) =>
    transport.post<ApiResponse<KnowledgeGraph>>(`/novel-ai/graph/rebuild/${novelId}`),
}
