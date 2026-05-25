export interface ApiResponse<T> {
  success: boolean
  data: T | null
  message: string
}

export interface PaginatedResponse<T> {
  success: boolean
  data: T[]
  total: number
  page: number
  page_size: number
}

export interface Project {
  id: number
  title: string
  description: string | null
  genre: string | null
  owner_id: number
  synopsis: string | null
  outline: string | null
  total_episodes: number | null
  ai_config_id: number | null
  system_prompt: string | null
  created_at: string
  updated_at: string
}

export interface Character {
  id: number
  name: string
  role: string | null
  description: string | null
  project_id: number
  created_at: string
  updated_at: string
}

export interface Episode {
  id: number
  title: string
  episode_number: number
  synopsis: string | null
  project_id: number
  created_at: string
  updated_at: string
}

export interface Script {
  id: number
  version: number
  status: string
  content: string | null
  ai_prompt: string | null
  episode_id: number
  created_at: string
  updated_at: string
}

export interface AIConfig {
  id: number
  name: string
  base_url: string
  api_key: string
  model: string
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface AIPromptPreset {
  id: number
  name: string
  content: string
  is_global: boolean
  created_at: string
  updated_at: string
}

export interface OutlineEpisode {
  episode_number: number
  title: string
  synopsis: string
}

export interface OutlineResult {
  total_episodes: number
  theme: string
  episodes: OutlineEpisode[]
}

export interface Novel {
  id: number
  title: string
  genre: string | null
  synopsis: string
  outline: string | null
  knowledge_graph: string | null
  total_chapters: number | null
  owner_id: number
  ai_config_id: number | null
  system_prompt: string | null
  created_at: string
  updated_at: string | null
}

export interface Chapter {
  id: number
  title: string
  chapter_number: number
  synopsis: string | null
  novel_id: number
  created_at: string
  updated_at: string | null
}

export interface ChapterContent {
  id: number
  content: string | null
  word_count: number
  status: string
  version: number
  chapter_id: number
  created_at: string
  updated_at: string | null
}

export interface ChapterOutlineItem {
  chapter_number: number
  title: string
  synopsis: string
}

export interface NovelOutlineResult {
  total_chapters: number
  theme: string
  chapters: ChapterOutlineItem[]
}

export interface ConversionEpisode {
  episode_number: number
  title: string
  script: string
  duration_estimate: string
}

export interface NovelToScriptResult {
  total_episodes: number
  episodes: ConversionEpisode[]
}

export interface VideoScriptScene {
  scene_number: number
  description: string
  duration: string
  camera_angle: string
  lighting: string
}

export interface ScriptToVideoResult {
  scenes: VideoScriptScene[]
  total_duration: string
}
