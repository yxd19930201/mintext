import { create } from 'zustand'
import { novelApi } from '../services/api/novelApi'
import { chapterApi } from '../services/api/chapterApi'
import type { Novel, Chapter } from '../types/models'
import { clearPersistentTaskPrefix } from './persistentTaskStore'

interface NovelState {
  novels: Novel[]
  currentNovel: Novel | null
  chapters: Chapter[]
  loading: boolean
  error: string | null
  activeNovelId: number | null
  fetchNovels: () => Promise<void>
  fetchNovel: (id: number) => Promise<void>
  createNovel: (data: { title: string; genre?: string; synopsis: string; total_chapters?: number }) => Promise<Novel>
  deleteNovel: (id: number) => Promise<void>
  fetchChapters: (novelId: number) => Promise<void>
  createChapter: (novelId: number, data: { title: string; chapter_number: number; synopsis?: string }) => Promise<Chapter>
}

export const useNovelStore = create<NovelState>((set, get) => ({
  novels: [],
  currentNovel: null,
  chapters: [],
  loading: false,
  error: null,
  activeNovelId: null,

  fetchNovels: async () => {
    set({ loading: true, error: null })
    try {
      const res = await novelApi.list()
      set({ novels: res.data, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  fetchNovel: async (id) => {
    set({ activeNovelId: id, currentNovel: null, loading: true, error: null })
    try {
      const res = await novelApi.get(id)
      if (get().activeNovelId === id) set({ currentNovel: res.data, loading: false })
    } catch (e) {
      if (get().activeNovelId === id) set({ error: String(e), loading: false })
    }
  },

  createNovel: async (data) => {
    const res = await novelApi.create(data)
    const novel = res.data!
    clearPersistentTaskPrefix(`novel:${novel.id}:`)
    set({ novels: [...get().novels, novel] })
    return novel
  },

  deleteNovel: async (id) => {
    await novelApi.delete(id)
    clearPersistentTaskPrefix(`novel:${id}:`)
    set({
      novels: get().novels.filter((n) => n.id !== id),
      ...(get().activeNovelId === id
        ? { activeNovelId: null, currentNovel: null, chapters: [] }
        : {}),
    })
  },

  fetchChapters: async (novelId) => {
    set({ activeNovelId: novelId, chapters: [], loading: true, error: null })
    try {
      const res = await chapterApi.list(novelId)
      if (get().activeNovelId === novelId) {
        set({ chapters: res.data || [], loading: false })
      }
    } catch (e) {
      if (get().activeNovelId === novelId) set({ error: String(e), loading: false })
    }
  },

  createChapter: async (novelId, data) => {
    const res = await chapterApi.create(novelId, data)
    const chapter = res.data!
    set({ chapters: [...get().chapters, chapter].sort((a, b) => a.chapter_number - b.chapter_number) })
    return chapter
  },
}))
