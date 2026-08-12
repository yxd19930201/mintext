import { transport } from './index'
import type { ApiResponse } from '../../types/models'
import { getGenerationOptions } from '../generationMode'

export type InspectionType = 'quality' | 'ai_trace'

export interface ManuscriptDocument {
  name: string
  content: string
  chapter_number?: number
}

export interface ManuscriptReportSummary {
  id: number
  inspection_type: InspectionType
  source_name: string
  novel_id: number | null
  word_count: number
  overall_score: number
  verdict: string
  status: string
  completed_chapters: number
  total_chapters: number
  created_at: string
}

export interface ManuscriptReport extends Omit<ManuscriptReportSummary, 'overall_score' | 'verdict' | 'status' | 'completed_chapters' | 'total_chapters'> {
  report: Record<string, any>
}

export const manuscriptApi = {
  inspect: (data: {
    inspection_type: InspectionType
    novel_id?: number
    source_name?: string
    source_text?: string
    source_documents?: ManuscriptDocument[]
    ai_config_id?: number
  }) => transport.post<ApiResponse<ManuscriptReport>>('/manuscript/inspect', {
    ...data,
    ...getGenerationOptions(),
  }),
  listReports: () => transport.get<ApiResponse<ManuscriptReportSummary[]>>('/manuscript/reports'),
  getReport: (reportId: number) => transport.get<ApiResponse<ManuscriptReport>>(`/manuscript/reports/${reportId}`),
  deleteReport: (reportId: number) => transport.delete<void>(`/manuscript/reports/${reportId}`),
}
