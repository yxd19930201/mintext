export type GenerationMode = 'economy' | 'strict' | 'free'
export type FreeProvider = 'deepseek' | 'chatgpt'

export interface GenerationOptions {
  generation_mode: GenerationMode
  economy_mode: boolean
  free_mode: boolean
  free_provider: FreeProvider
}

/** Read the mode at the exact moment an AI job is submitted. */
export const getGenerationOptions = (): GenerationOptions => {
  const stored = localStorage.getItem('mintext:generationMode')
  const generationMode: GenerationMode =
    stored === 'strict' || stored === 'free' ? stored : 'economy'
  const provider = localStorage.getItem('mintext:freeProvider')
  const freeProvider: FreeProvider = provider === 'chatgpt' ? 'chatgpt' : 'deepseek'
  return {
    generation_mode: generationMode,
    economy_mode: generationMode !== 'strict',
    free_mode: generationMode === 'free',
    free_provider: freeProvider,
  }
}
