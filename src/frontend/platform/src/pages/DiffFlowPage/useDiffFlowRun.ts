/**
 * Fetching + SSE orchestration for the version-diff page. The store
 * (@/store/diffFlowStore) only holds state (C7); everything network-bound
 * lives here.
 */
import { getVersionDetails } from "@/controllers/API/flow";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useDiffFlowStore } from "@/store/diffFlowStore";

declare const __APP_ENV__: { BASE_URL: string };

interface CellHandle {
    loading(): void;
    loaded(): void;
    setData(data: unknown): void;
}

interface RunTestArgs {
    questions: { q: string }[];
    questionIndexs: number[];
    versionIds: string[];
    nodeId: string;
    inputs: unknown;
    refs: Record<string, { current: CellHandle }>;
}

/** Streams one test run over SSE, feeding each answer into its cell ref. */
function runTest({ questions, questionIndexs, nodeId, versionIds, inputs, refs }: RunTestArgs): Promise<unknown> {
    const runIds: string[] = [];
    questionIndexs.forEach(qIndex => {
        versionIds.forEach(versionId => {
            refs[`${qIndex}-${versionId}`].current.loading();
            runIds.push(`${qIndex}-${versionId}`);
        });
    });

    const data = JSON.stringify({
        question_list: questionIndexs.map(qIndex => questions[qIndex].q),
        version_list: versionIds,
        inputs,
        node_id: nodeId,
    });

    return new Promise((resolve, reject) => {
        const apiUrl = `${__APP_ENV__.BASE_URL}/api/v1/flows/compare/stream?data=${encodeURIComponent(data)}`;
        const eventSource = new EventSource(apiUrl);

        eventSource.onmessage = (event) => {
            if (!event.data) return;
            const parsedData = JSON.parse(event.data);
            const { type, question_index, version_id, answer } = parsedData;
            if (!type) {
                refs[`${questionIndexs[question_index]}-${version_id}`].current.setData(answer);
            } else if (type === 'end') {
                resolve('');
            }
        };

        eventSource.onerror = (error) => {
            console.error('event :>> ', error);
            eventSource.close();
            runIds.forEach(id => {
                refs[id].current.loaded();
            });
            reject(error);
        };
    });
}

export function useDiffFlowRun() {
    const initFristVersionFlow = (versionId: string) => {
        captureAndAlertRequestErrorHoc(getVersionDetails(versionId).then(version => {
            useDiffFlowStore.getState().resetWithFirstVersion(version);
        }));
    };

    const addVersionFlow = (versionId: string, index: number) => {
        useDiffFlowStore.getState().flagVersionReady(versionId);
        captureAndAlertRequestErrorHoc(getVersionDetails(versionId).then(version => {
            useDiffFlowStore.getState().fillVersionFlow(index, version);
        }));
    };

    const allRunStart = async (nodeId: string, inputs: unknown) => {
        const store = useDiffFlowStore.getState();
        store.beginAllRun();
        const { questions, mulitVersionFlow, cellRefs } = useDiffFlowStore.getState();
        await runTest({
            questions,
            questionIndexs: questions.map((_, index) => index),
            versionIds: mulitVersionFlow.filter(el => el).map(version => version?.id),
            nodeId,
            inputs,
            refs: cellRefs,
        });
        useDiffFlowStore.getState().endRun();
    };

    const rowRunStart = async (qIndex: number, nodeId: string, inputs: unknown) => {
        useDiffFlowStore.getState().beginRowRun(qIndex);
        const { questions, mulitVersionFlow, cellRefs } = useDiffFlowStore.getState();
        await runTest({
            questions,
            questionIndexs: [qIndex],
            versionIds: mulitVersionFlow.filter(el => el).map(version => version?.id),
            nodeId,
            inputs,
            refs: cellRefs,
        });
        useDiffFlowStore.getState().endRun();
    };

    const colRunStart = async (versionId: string, nodeId: string, inputs: unknown) => {
        useDiffFlowStore.getState().beginColRun(versionId);
        const { questions, cellRefs } = useDiffFlowStore.getState();
        await runTest({
            questions,
            questionIndexs: questions.map((_, index) => index),
            versionIds: [versionId],
            nodeId,
            inputs,
            refs: cellRefs,
        });
        useDiffFlowStore.getState().endRun();
    };

    return { initFristVersionFlow, addVersionFlow, allRunStart, rowRunStart, colRunStart };
}
