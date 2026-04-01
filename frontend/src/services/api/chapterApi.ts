import { transport } from './index'
import type { ApiResponse, Chapter } from '../../types/models'

export const chapterApi = {
  list: (novelId: number) =>
    transport.get<ApiResponse<Chapter[]>>(`/novels/${novelId}/chapters`),

  create: (novelId: number, data: {
    title: string
    chapter_number: number
    synopsis?: string
  }) =>
    transport.post<ApiResponse<Chapter>>(`/novels/${novelId}/chapters`, data),

  update: (novelId: number, chapterId: number, data: Partial<{
    title: string
    synopsis: string
  }>) =>
    transport.patch<ApiResponse<Chapter>>(`/novels/${novelId}/chapters/${chapterId}`, data),

  delete: (novelId: number, chapterId: number) =>
    transport.delete<void>(`/novels/${novelId}/chapters/${chapterId}`),
}
