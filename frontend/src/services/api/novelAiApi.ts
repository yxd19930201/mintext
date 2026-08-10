import { transport } from './index'
import type { ApiResponse, NovelOutlineResult } from '../../types/models'

const economyMode = () => localStorage.getItem('mintext:generationMode') !== 'strict'

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

export type CanonRecord = Record<string, unknown>

export interface CanonArchive extends KnowledgeGraph {
  current_chapter: number
  time_place: string
  protagonist: CanonRecord
  supporting_characters: CanonRecord[]
  relationship_states: CanonRecord[]
  dialogue_profiles: Record<string, CanonRecord>
  asset_accounts: CanonRecord[]
  transaction_ledger: CanonRecord[]
  item_custody: CanonRecord[]
  timeline: CanonRecord[]
  knowledge_boundaries: CanonRecord[]
  commitments: CanonRecord[]
  plot_threads: CanonRecord[]
  canon_facts: CanonRecord[]
  manual_edit_history: CanonRecord[]
}

export type CanonArchiveSection =
  | 'protagonist'
  | 'characters'
  | 'events'
  | 'supporting_characters'
  | 'relationship_states'
  | 'dialogue_profiles'
  | 'asset_accounts'
  | 'transaction_ledger'
  | 'item_custody'
  | 'timeline'
  | 'knowledge_boundaries'
  | 'commitments'
  | 'plot_threads'
  | 'canon_facts'

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
    transport.post<ApiResponse<NovelOutlineResult>>('/novel-ai/generate/outline', {
      ...data,
      economy_mode: economyMode(),
    }),

  generateChapter: (chapterId: number, data: {
    extra_context?: string
    ai_config_id?: number
    system_prompt?: string
    regenerate?: boolean
    restart_failed_generation?: boolean
  }) =>
    transport.post<ApiResponse<GenerateChapterResult>>(`/novel-ai/generate/chapter/${chapterId}`, {
      ...data,
      economy_mode: economyMode(),
    }),

  batchGenerate: (novelId: number, data: {
    only_missing?: boolean
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<BatchGenerateResult>>(`/novel-ai/generate/batch/${novelId}`, {
      ...data,
      economy_mode: economyMode(),
    }),

  generateNext: (novelId: number, data: {
    ai_config_id?: number
    system_prompt?: string
  }) =>
    transport.post<ApiResponse<GenerateNextChapterResult>>(`/novel-ai/generate/next/${novelId}`, {
      ...data,
      economy_mode: economyMode(),
    }),

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

  getArchive: (novelId: number) =>
    transport.get<ApiResponse<CanonArchive>>(`/novel-ai/archive/${novelId}`),

  updateArchiveSection: (
    novelId: number,
    section: CanonArchiveSection,
    data: CanonRecord[] | CanonRecord | Record<string, CanonRecord>,
  ) =>
    transport.patch<ApiResponse<CanonArchive>>(`/novel-ai/archive/${novelId}/${section}`, { data }),
}
