import { create } from 'zustand'
import { projectApi } from '../services/api/projectApi'
import type { Project } from '../types/models'

interface ProjectState {
  projects: Project[]
  loading: boolean
  error: string | null
  fetchProjects: () => Promise<void>
  createProject: (data: { title: string; description?: string; genre?: string; synopsis?: string; total_episodes?: number }) => Promise<Project>
  deleteProject: (id: number) => Promise<void>
}

export const useProjectStore = create<ProjectState>((set, get) => ({
  projects: [],
  loading: false,
  error: null,

  fetchProjects: async () => {
    set({ loading: true, error: null })
    try {
      const res = await projectApi.list()
      set({ projects: res.data, loading: false })
    } catch (e) {
      set({ error: String(e), loading: false })
    }
  },

  createProject: async (data) => {
    const res = await projectApi.create(data)
    const project = res.data!
    set({ projects: [...get().projects, project] })
    return project
  },

  deleteProject: async (id) => {
    await projectApi.delete(id)
    set({ projects: get().projects.filter((p) => p.id !== id) })
  },
}))
