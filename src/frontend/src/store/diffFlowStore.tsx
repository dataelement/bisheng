/**
 * 技能组件版本效果对比
 */
import { generateUUID } from "@/components/bs-ui/utils"
import { getVersionDetails, runTestCase } from "@/controllers/API/flow"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { create } from "zustand"

const enum RunningType {
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
    /** 初始化版本技能 */
    initFristVersionFlow(versionId: string): void,
    /** 添加空的对比版本 */
    addEmptyVersionFlow(): void,
    /** 添加对比版本技能 */
    addVersionFlow(versionId: string, index: number): void,
    /** 移除对比版本技能 */
    removeVersionFlow(index: number): void,
    /** 更新版本运行状态 */
    // updateReadyVersions(version: string): void,
    /** 上传覆盖问题列表 */
    overQuestions(list: string[]): void,
    /** 添加问题 */
    addQuestion(q: string): void
}

export const useDiffFlowStore = create<State & Actions>((set, get) => ({
    mulitVersionFlow: [],
    questions: [],
    readyVersions: {},
    running: false,
    runningType: RunningType.None,
    cellRefs: {},
    initFristVersionFlow(versionId) {
        getVersionDetails(versionId).then(version => {
            set({
                mulitVersionFlow: [version, null],
                questions: [],
                readyVersions: {},
                running: false,
                runningType: RunningType.None,
                cellRefs: {},
            })
        })
    },
    addEmptyVersionFlow() {
        set((state) => ({ mulitVersionFlow: [...state.mulitVersionFlow, null] }))
    },
    addVersionFlow(versionId, index) {
        const { running, readyVersions } = get()
        // 标记可运行状态
        if (running) {
            set({ readyVersions: { ...readyVersions, [versionId]: true } })
        }

        getVersionDetails(versionId).then(version => {
            set((state) => {
                // 填充flow
                state.mulitVersionFlow[index] = version
                return { mulitVersionFlow: [...state.mulitVersionFlow] }
            })
        })
    },
    removeVersionFlow(index) {
        set((state) => ({
            mulitVersionFlow:
                state.mulitVersionFlow.filter((_, i) => i !== index)
        }))
    },
    // updateReadyVersions(version) {
    //     if (get().running) {
    //         set((state) => ({
    //             readyVersions: {
    //                 ...state.readyVersions,
    //                 [version]: true
    //             }
    //         }))
    //     }
    // },
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
    async allRunStart(nodeId, inputs) {
        set((state) => ({
            readyVersions: {},
            questions: state.questions.map(el => ({ ...el, ready: false })),
            runningType: RunningType.All,
            running: true
        }))
        const questions = get().questions
        const versions = get().mulitVersionFlow

        await runTest({
            questions,
            questionIndexs: questions.map((_, index) => index),
            versionIds: versions.filter(el => el).map(version => version?.id),
            nodeId,
            inputs,
            refs: get().cellRefs
        })
        set({ runningType: RunningType.None })
    },
    async rowRunStart(qIndex, nodeId, inputs) {
        set((state) => ({
            questions: state.questions.map((el, i) => qIndex === i ? { ...el, ready: false } : el),
            runningType: RunningType.Row
        }))
        const questions = get().questions
        const versions = get().mulitVersionFlow

        await runTest({
            questions,
            questionIndexs: [qIndex],
            versionIds: versions.filter(el => el).map(version => version?.id),
            nodeId,
            inputs,
            refs: get().cellRefs
        })
        set({ runningType: RunningType.None })
    },
    async colRunStart(versionId, nodeId, inputs) {
        set((state) => ({
            readyVersions: { ...state.readyVersions, [versionId]: false },
            runningType: RunningType.Col
        }))
        const questions = get().questions

        await runTest({
            questions,
            questionIndexs: questions.map((_, index) => index),
            versionIds: [versionId],
            nodeId,
            inputs,
            refs: get().cellRefs
        })
        set({ runningType: RunningType.None })
    }
}))


/**
 * 运行测试用例
 * @param questions 所有问题列表
 * @param questionIndexs 问题索引
 * @param nodeId 节点id
 * @param versionIds 版本id
 * @param refs 单元格ref
 */
const runTest = ({ questions, questionIndexs, nodeId, versionIds, inputs, refs }) => {
    // loading
    // console.log(refs, 222);
    const runIds = []
    questionIndexs.forEach(qIndex => {
        versionIds.forEach(versionId => {
            refs[`${qIndex}-${versionId}`].current.loading()
            runIds.push(`${qIndex}-${versionId}`)
        })
    });
    // 运行
    const data = JSON.stringify({
        question_list: questionIndexs.map(qIndex => questions[qIndex].q),
        version_list: versionIds,
        inputs,
        node_id: nodeId
    })

    return new Promise((resolve, reject) => {
        const apiUrl = `${__APP_ENV__.BASE_URL}/api/v1/flows/compare/stream?data=${encodeURIComponent(data)}`;
        const eventSource = new EventSource(apiUrl);

        eventSource.onmessage = (event) => {
            if (!event.data) {
                return;
            }
            const parsedData = JSON.parse(event.data);
            const { type, question_index, version_id, answer } = parsedData;
            if (!type) {
                refs[`${questionIndexs[question_index]}-${version_id}`].current.setData(answer)
            } else if (type === 'end') {
                resolve('')
            }
        }

        eventSource.onerror = (error: any) => {
            console.error('event :>> ', error);
            eventSource.close();
            runIds.forEach(id => {
                refs[id].current.loaded()
            })

            reject(error);
        }
    })
    // runTestCaseStream()
    // return captureAndAlertRequestErrorHoc(runTestCase({
    //     question_list: questionIndexs.map(qIndex => questions[qIndex].q),
    //     version_list: versionIds,
    //     inputs,
    //     node_id: nodeId
    // }).then(data => {
    //     data.forEach((row, rowIndex) => {
    //         Object.keys(row).forEach(vId => {
    //             refs[`${questionIndexs[rowIndex]}-${vId}`].current.setData(row[vId])
    //         })
    //     })
    // }), () => {
    //     // error callback
    //     runIds.forEach(id => {
    //         refs[id].current.loaded()
    //     })
    // })
}