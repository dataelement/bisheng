import { AssistantDetail } from '@/types/assistant'
import { create } from 'zustand'

/**
 * 助手编辑管理
 */

type State = {
  assistantState: AssistantDetail
}

type Actions = {
  dispatchAssistant: (action: Action, assistantState: Partial<AssistantDetail>) => void,
  loadAssistantState: () => void
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
  loadAssistantState: () => {
    // api
    set({
      assistantState: {
        id: 3,
        name: "测试助手002",
        desc: "这是一个示例助手描述。",
        logo: "path/to/logo.png",
        prompt: "用户可见的临时prompt",
        guide_word: "欢迎使用我们的助手！",
        guide_question: [],
        model_name: "gpt-4-0125-preview2",
        temperature: 0.5,
        status: 0,
        user_id: 1,
        create_time: "2024-03-27T14:57:33",
        update_time: "2024-03-27T14:57:33",
        tool_list: [],
        flow_list: [],
        knowledge_list: [],
      }
    })

    return Promise.resolve()
  }
}))