import { AssistantDetail } from '@/types/assistant'
import { create } from 'zustand'
import { getAssistantDetailApi } from '../controllers/API/assistant'

/**
 * 助手编辑管理
 */

type State = {
  assistantState: AssistantDetail
}

type Actions = {
  dispatchAssistant: (action: Action, assistantState: Partial<AssistantDetail>) => void,
  loadAssistantState: (id: string) => void
}

type Action = 'setBaseInfo' | 'setting' | 'setPrompt' | 'setGuideword' | 'setTools' | 'setFlows'

const assistantReducer = (state: State, action: Action, data: Partial<AssistantDetail>) => {
  console.log('action :>> ', action, data);
  return { assistantState: { ...state.assistantState, ...data } }
  // switch (action) {
  //   case 'setBaseInfo':
  //     return { assistantState: { ...state.assistantState, ...data } }
  //   default:
  //     return state
  // }
}

export const useAssistantStore = create<State & Actions>((set) => ({
  assistantState: {
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
  },
  dispatchAssistant: (action: Action, data: Partial<AssistantDetail>) => set((state) => assistantReducer(state, action, data)),
  // 加载助手状态
  loadAssistantState: (id) => {
    return getAssistantDetailApi(id).then(data => {
      set({ assistantState: { ...data, guide_question: data.guide_question || [] } })
    })
  }
}))