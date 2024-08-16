import { AssistantDetail } from '@/types/assistant'
import { create } from 'zustand'
import { getAssistantDetailApi } from '../controllers/API/assistant'

/**
 * 助手编辑管理
 */

type State = {
  changed: boolean,
  assistantState: AssistantDetail
}

type Actions = {
  dispatchAssistant: (action: Action, assistantState: Partial<AssistantDetail>) => void,
  loadAssistantState: (id: string, version: string) => Promise<any>
  saveAfter: () => void
  destroy: () => void
}

type Action = 'setBaseInfo' | 'setting' | 'setPrompt' | 'setGuideword' | 'setTools' | 'setFlows' | 'setQuestion' | 'setContentSecurity'

const assistantReducer = (state: State, action: Action, data: Partial<AssistantDetail>) => {
  console.log('action :>> ', action, data);
  return { changed: true, assistantState: { ...state.assistantState, ...data } }
  // switch (action) {
  //   case 'setBaseInfo':
  //     return { assistantState: { ...state.assistantState, ...data } }
  //   default:
  //     return state
  // }
}


const assistantTemp = {
  id: 3,
  name: "",
  desc: "",
  logo: "",
  prompt: "",
  guide_word: "",
  guide_question: [],
  model_name: "",
  temperature: 0.5,
  status: 0,
  user_id: 1,
  create_time: "",
  update_time: "",
  tool_list: [],
  flow_list: [],
  knowledge_list: [],
}

export const useAssistantStore = create<State & Actions>((set) => ({
  changed: false,
  assistantState: { ...assistantTemp },
  dispatchAssistant: (action: Action, data: Partial<AssistantDetail>) => set((state) => assistantReducer(state, action, data)),
  // 加载助手状态
  loadAssistantState: (id, version) => {
    return getAssistantDetailApi(id, version).then(data => {
      set({
        assistantState: {
          ...data,
          model_name: Number(data.model_name),
          // 补一个空行
          guide_question: data.guide_question ? [...data.guide_question, ''] : ['']
        }
      })
      return data
    })
  },
  saveAfter() {
    set({ changed: false })
  },
  destroy: () => {
    set({ assistantState: { ...assistantTemp } })
  }
}))