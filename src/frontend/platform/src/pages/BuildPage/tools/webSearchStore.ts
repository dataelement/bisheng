// src/stores/webSearchStore.ts
import { create } from 'zustand'

interface WebSearchConfig {
  enabled: boolean
  tool: string
  bing: { type: string; config: { api_key: string; base_url: string } }
  bocha: { type: string; config: { api_key: string } }
   jina: { type: string; config: { api_key: string } }
    serp: { type: string; config: { api_key: string;  engine: string } }
     tavily: { type: string; config: { api_key: string } }
  prompt: string
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