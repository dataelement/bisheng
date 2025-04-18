import { create } from 'zustand'
import cloneDeep from "lodash-es/cloneDeep";

/**
 * 流程编排管理
 */

type State = {
    /** 流程对象 */
    originFlow: any
    /** clone flow,用于保存前的编辑对象 */
    flow: any
    /** 序列化的 flow, 用来对比是否修改 */
    serializedFlow: string
    /** 正在编辑的流程节点 */
    eidtFlowNode: any
}

type Actions = {
    /** 切换技能重新加载flow数据 */
    loadFlow: (flowId: string) => void
}

type Action = ''

const assistantReducer = (state: State, action: Action, data: any) => {
    console.log('action :>> ', action, data);
    //   return { changed: true, assistantState: { ...state.assistantState, ...data } }
    // switch (action) {
    //   case 'setBaseInfo':
    //     return { assistantState: { ...state.assistantState, ...data } }
    //   default:
    //     return state
    // }
}

const temp = {}

export const useEditFlowStore = create<State & Actions>((set, get) => ({
    originFlow: null,
    flow: null,
    serializedFlow: '',
    eidtFlowNode: null,
    loadFlow(id) {
        const { flow } = get()
        // 相同的 flow不再加载
        if (id && flow?.id !== id) {
            // getFlowApi(id).then(_flow => setFlow('flow_init', _flow))
            const originFlow = { ...temp }
            set({ originFlow: originFlow, flow: cloneDeep(originFlow), serializedFlow: JSON.stringify(originFlow) })
        }
    }
}))