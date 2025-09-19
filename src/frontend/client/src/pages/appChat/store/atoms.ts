import { atom, selector } from "recoil"
import type { BishengConfig, Chat, RunningStatus, SubmitData, WebSocketStatus } from "~/@types/chat"

// 所有会话数据的Map存储  (key: chatId) 
/**
 * map
 */
export const chatsState = atom<Record<string, Chat>>({
    key: "chatsMapState",
    default: {},
})

export const chatIdState = atom<string>({
    key: "chatIdState",
    default: '',
})

// 获取当前会话信息
export const currentChatState = selector<Chat | null>({
    key: "currentChatState",
    get: ({ get }) => {
        const chatsMap = get(chatsState)
        const currentChatId = get(chatIdState)

        if (!currentChatId) return null
        return chatsMap[currentChatId] || null
    },
})


// 会话上传的文件
export const chatUploadFileState = atom<File[]>({
    key: "chatUploadFileState",
    default: [],
})

// UI状态管理
export const runningState = atom<Record<string, RunningStatus>>({
    key: "runningState",
    default: {},
})

// 获取当前会话状态
export const currentRunningState = selector<RunningStatus | null>({
    key: "currentRunningStateSelector",
    get: ({ get }) => {
        const runningStateMap = get(runningState)
        const currentChatId = get(chatIdState)

        if (!currentChatId) return null
        return runningStateMap[currentChatId] || null
    },
})


// 提交数据
export const submitDataState = atom<SubmitData | null>({
    key: "submitDataState",
    default: null,
})

// 会话文件
export const chatFileState = atom<{ name: string, path: string }[]>({
    key: "chatFileState",
    default: [],
})

// 毕昇配置信息
export const bishengConfState = atom<BishengConfig | null>({
    key: "bishengConfState",
    default: null,
})

export const webSocketStatusState = atom<Record<string, WebSocketStatus>>({
    key: "webSocketStatusState",
    default: {},
})

export const errorState = atom<Record<string, string>>({
    key: "errorState",
    default: {},
})

export const tabsState = atom<any>({
    key: "tabsState",
    default: {
        flow: null,
        tabsState: {}, // keyform isPending
        setFlow: (ac, f) => { },
        setTabsState: (state) => { },
        saveFlow: async (flow) => Promise.resolve(),
        uploadFlow: () => { },
        setTweak: (tweak: any) => { },
        getTweak: [],
        // 跨组件粘贴
        lastCopiedSelection: null,
        setLastCopiedSelection: (selection: any) => { },
        downloadFlow: (flow) => { },
        getNodeId: (nodeType: string) => "",
        paste: (
            selection: { nodes: any; edges: any },
            position: { x: number; y: number; paneX?: number; paneY?: number }
        ) => { },
        version: null,
        setVersion: (version) => ""
    }
})