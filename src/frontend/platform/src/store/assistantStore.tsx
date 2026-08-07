import { AssistantDetail } from '@/types/assistant'
import { create } from 'zustand'

/**
 * 助手编辑管理
 */

type State = {
  changed: boolean,
  assistantState: AssistantDetail
}

type Actions = {
  dispatchAssistant: (action: Action, assistantState: Partial<AssistantDetail>) => void,
  // C7: callers fetch via getAssistantDetailApi and hand the payload in here.
  setAssistantDetail: (data: AssistantDetail) => void
  saveAfter: () => void
  destroy: () => void
}

type Action = 'setBaseInfo' | 'setting' | 'setPrompt' | 'setGuideword' | 'setTools' | 'setFlows' | 'setQuestion' | 'setContentSecurity'

const assistantReducer = (state: State, action: Action, data: Partial<AssistantDetail>) => {
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
  temperature: 1,
  status: 0,
  user_id: 1,
  create_time: "",
  update_time: "",
  tool_list: [],
  flow_list: [],
  knowledge_list: [],
  max_token: 32000
}

export const useAssistantStore = create<State & Actions>((set) => ({
  changed: false,
  assistantState: { ...assistantTemp },
  dispatchAssistant: (action: Action, data: Partial<AssistantDetail>) => set((state) => assistantReducer(state, action, data)),
  setAssistantDetail: (data) => {
    set({
      assistantState: {
        ...data,
        model_name: Number(data.model_name),
        // trailing empty slot for the guide-question editor
        guide_question: data.guide_question ? [...data.guide_question, ''] : ['']
      }
    })
  },
  saveAfter() {
    set({ changed: false })
  },
  changeStatus(status) {
    set((state) => ({
      assistantState: {
        ...state.assistantState,
        status: status
      }
    }));
  },
  destroy: () => {
    set({ assistantState: { ...assistantTemp } })
  }
}))
