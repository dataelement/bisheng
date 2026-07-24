// @ts-strict-ignore
/**
 * 技能组件版本效果对比
 * Pure state only (C7): fetching + SSE orchestration live in
 * pages/DiffFlowPage/useDiffFlowRun.ts and hand results in here.
 */
import { generateUUID } from "@/components/bs-ui/utils"
import { create } from "zustand"

export const enum RunningType {
    /** 全量对比 */
    All = 'all',
    /** 列对比 */
    Col = 'col',
    /** 行对比 */
    Row = 'row',
    /** 无对比 */
    None = ''
}

type State = {
    mulitVersionFlow: any[],
    /** 用例问题列表 */
    questions: { id: string, q: string, ready: boolean }[],
    /** 运行过一次 */
    running: boolean,
    /** 测试运行按钮状态 */
    runningType: RunningType,
    /** 版本运行按钮状态 */
    readyVersions: { [verstion in string]: boolean }
    /** 单元格ref */
    cellRefs: { [key in string]: any }
}

type Actions = {
    /** 初始化版本技能(载荷由调用方获取) */
    resetWithFirstVersion(version: unknown): void,
    /** 添加空的对比版本 */
    addEmptyVersionFlow(): void,
    /** 填充对比版本技能(载荷由调用方获取) */
    fillVersionFlow(index: number, version: unknown): void,
    /** 运行中补选版本时标记其可运行 */
    flagVersionReady(versionId: string): void,
    /** 移除对比版本技能 */
    removeVersionFlow(index: number): void,
    /** 上传覆盖问题列表 */
    overQuestions(list: string[]): void,
    /** 添加问题 */
    addQuestion(q: string): void,
    /** 进入/退出运行态(编排在 useDiffFlowRun) */
    beginAllRun(): void,
    beginRowRun(qIndex: number): void,
    beginColRun(versionId: string): void,
    endRun(): void,
}

export const useDiffFlowStore = create<State & Actions>((set, get) => ({
    mulitVersionFlow: [],
    questions: [],
    readyVersions: {},
    running: false,
    runningType: RunningType.None,
    cellRefs: {},
    resetWithFirstVersion(version) {
        set({
            mulitVersionFlow: [version, null],
            questions: [],
            readyVersions: {},
            running: false,
            runningType: RunningType.None,
            cellRefs: {},
        })
    },
    addEmptyVersionFlow() {
        set((state) => ({ mulitVersionFlow: [...state.mulitVersionFlow, null] }))
    },
    fillVersionFlow(index, version) {
        set((state) => {
            state.mulitVersionFlow[index] = version
            return { mulitVersionFlow: [...state.mulitVersionFlow] }
        })
    },
    flagVersionReady(versionId) {
        const { running, readyVersions } = get()
        if (running) {
            set({ readyVersions: { ...readyVersions, [versionId]: true } })
        }
    },
    removeVersionFlow(index) {
        set((state) => ({
            mulitVersionFlow:
                state.mulitVersionFlow.filter((_, i) => i !== index)
        }))
    },
    overQuestions(list) {
        set(() => ({
            questions: list.splice(0, 20).map(q => ({
                id: generateUUID(5),
                q,
                ready: get().running
            }))
        }))
    },
    addQuestion(q) {
        set((state) => ({
            questions: [...state.questions, { q, id: generateUUID(5), ready: get().running }]
        }))
    },
    updateQuestion(q, index) {
        set((state) => ({
            questions: state.questions.map((el, i) => i === index ? { ...el, q, ready: get().running } : el)
        }))
    },
    removeQuestion(index) {
        set((state) => ({
            questions: state.questions.filter((_, i) => i !== index)
        }))
    },
    addCellRef: (key, ref) => {
        set(state => {
            return { cellRefs: { ...state.cellRefs, [key]: ref } };
        })
    },
    removeCellRef: (key) => set(state => {
        const newCellRefs = { ...state.cellRefs }
        delete newCellRefs[key]
        return { cellRefs: newCellRefs };
    }),
    beginAllRun() {
        set((state) => ({
            readyVersions: {},
            questions: state.questions.map(el => ({ ...el, ready: false })),
            runningType: RunningType.All,
            running: true
        }))
    },
    beginRowRun(qIndex) {
        set((state) => ({
            questions: state.questions.map((el, i) => qIndex === i ? { ...el, ready: false } : el),
            runningType: RunningType.Row
        }))
    },
    beginColRun(versionId) {
        set((state) => ({
            readyVersions: { ...state.readyVersions, [versionId]: false },
            runningType: RunningType.Col
        }))
    },
    endRun() {
        set({ runningType: RunningType.None })
    },
}))