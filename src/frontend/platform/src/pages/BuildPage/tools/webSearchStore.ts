// src/stores/webSearchStore.ts
import { create } from 'zustand'

// webSearchStore.ts
interface WebSearchConfig {
  type: string
  config: {
    bing: { api_key: string; base_url: string }
    bocha: { api_key: string }
    jina: { api_key: string }
    serp: { api_key: string; engine: string }
    tavily: { api_key: string }
  }
}

interface WebSearchStore {
  config: WebSearchConfig | null
  setConfig: (config: Partial<WebSearchConfig>) => void
}

export const useWebSearchStore = create<WebSearchStore>((set) => ({
  config: null,
  setConfig: (newConfig) => 
    set((state) => ({ 
      config: { ...state.config, ...newConfig } as WebSearchConfig 
    })),
}))