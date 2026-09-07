import { atom, selector } from "recoil"
import type { BishengConfig, Chat, RunningStatus, SubmitData, WebSocketStatus } from "~/@types/chat"

// Conversation data keyed by chatId.
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

// Resolve the current conversation.
export const currentChatState = selector<Chat | null>({
    key: "currentChatState",
    get: ({ get }) => {
        const chatsMap = get(chatsState)
        const currentChatId = get(chatIdState)

        if (!currentChatId) return null
        return chatsMap[currentChatId] || null
    },
})


// Files selected for upload in the current conversation.
export const chatUploadFileState = atom<File[]>({
    key: "chatUploadFileState",
    default: [],
})

// Per-conversation UI state.
export const runningState = atom<Record<string, RunningStatus>>({
    key: "runningState",
    default: {},
})

// Resolve the current conversation UI state.
export const currentRunningState = selector<RunningStatus | null>({
    key: "currentRunningStateSelector",
    get: ({ get }) => {
        const runningStateMap = get(runningState)
        const currentChatId = get(chatIdState)

        if (!currentChatId) return null
        return runningStateMap[currentChatId] || null
    },
})


// Current submission payload.
export const submitDataState = atom<SubmitData | null>({
    key: "submitDataState",
    default: null,
})

// Uploaded conversation files.
export const chatFileState = atom<{ name: string, path: string }[]>({
    key: "chatFileState",
    default: [],
})

// API version for chat endpoints (v1 = authenticated, v2 = key-authenticated, v3 = public guest).
export const chatApiVersionState = atom<'v1' | 'v2' | 'v3'>({
    key: "chatApiVersionState",
    default: 'v1',
})

// Runtime application configuration.
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
        // Cross-component paste state.
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
