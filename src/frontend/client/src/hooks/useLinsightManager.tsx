// @ts-strict-ignore
import { useCallback, useRef } from 'react';
import {
    useRecoilCallback,
    useRecoilState,
    useRecoilValue,
    useSetRecoilState
} from 'recoil';
import { continueLinsight, getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import store from '~/store';
import { activeSessionIdState, LinsightInfo, linsightMapState, SopStatus } from '~/store/linsight';
import { taskErrorInfoFromOutput } from '~/hooks/linsightErrorInfo';
/**
 * Backend SessionVersionStatusEnum values a run can no longer leave, i.e. the
 * ones that emit no further WS events. `waiting_for_user_input` is NOT one of
 * them — a parked run resumes — and neither is `not_started`, which means
 * queued. Kept as raw backend values (mapSessionVersionStatus maps them to the
 * store's SopStatus afterwards).
 */
const TERMINAL_SESSION_STATUSES = new Set([
    'completed',
    'failed',
    'terminated',
    'sop_generation_failed',
]);
export const useLinsightManager = () => {
    const [linsightMap, setLinsightMap] = useRecoilState(linsightMapState);
    const setActiveSessionId = useSetRecoilState(activeSessionIdState);
    const continuingVersions = useRef(new Set<string>());
    // 创建新会话信息
    const createLinsight = useCallback((versionId: string, initialData: Omit<LinsightInfo, 'id'>) => {
        const newLinsight: LinsightInfo = {
            id: versionId,
            ...initialData
        };
        setLinsightMap(prevMap => {
            const newMap = new Map(prevMap);
            newMap.set(versionId, newLinsight);
            return newMap;
        });
        setActiveSessionId(versionId);
        return versionId;
    }, [setLinsightMap, setActiveSessionId]);
    // 更新会话信息
    const updateLinsight = useCallback((versionId: string, update: Partial<LinsightInfo> | ((current: LinsightInfo) => Partial<LinsightInfo>)) => {
        setLinsightMap(prevMap => {
            if (!prevMap.has(versionId)) return prevMap;
            const newMap = new Map(prevMap);
            const current = newMap.get(versionId)!;

            // 处理update为函数的情况
            const updatedValue = typeof update === 'function'
                ? update(current)
                : update;

            newMap.set(versionId, {
                ...current,
                ...updatedValue
            });
            return newMap;
        });
    }, [setLinsightMap]);

    // 获取会话信息
    const getLinsight = (versionId: string) => {
        return linsightMap.get(versionId) || null;
    };

    /** Repair missed terminal events, without replacing a later conversation round. */
    const reconcileLinsightFromServer = useRecoilCallback(({ snapshot }) => async (versionId: string) => {
        const map = await snapshot.getPromise(linsightMapState);
        const current = map.get(versionId);
        // No session_id ⇒ nothing to query by (entry not hydrated yet).
        if (!current?.session_id) return false;

        const versions = await getLinsightSessionVersionList(current.session_id, '');
        const item = (versions || []).find((v) => String(v.id) === String(versionId));
        if (!item || !TERMINAL_SESSION_STATUSES.has(item.status)) return false;

        // Same shape the reload path builds (switchAndUpdateLinsight), so a
        // reconciled panel is indistinguishable from a freshly loaded one.
        const tasks = await getLinsightTaskList(versionId, item, '');
        let adopted = false;
        updateLinsight(versionId, (latest) => {
            // Continuing appends a new history array, retiring reads from the old round.
            if (latest.history !== current.history) return {};
            adopted = true;
            return {
                status: mapSessionVersionStatus(item.status, item.execute_feedback),
                output_result: item.output_result,
                execute_feedback: item.execute_feedback,
                tasks: buildTaskTree(tasks),
                file_list: item.output_result?.final_files || [],
                taskError: 'failed' === item.status ? item.output_result?.error_message : '',
                taskErrorInfo: taskErrorInfoFromOutput(item.status, item.output_result),
                // Carry the persisted task ChatMessage id + verdict, exactly as the
                // live final_result handler does, so like/dislike targets the right
                // row instead of a streaming placeholder.
                ...(item.message_id != null ? { message_id: item.message_id, liked: item.liked } : {}),
                queueCount: 0,
            };
        });
        return adopted;
    }, [updateLinsight]);

    // F035 多轮对话：在已完成的同一会话里追加新一轮。
    // 复用同一 session_version (versionId) + 同一 agent thread，后端保留全部上下文；
    // 前端把当前轮快照进 history，再清空顶层字段开新轮，WS 事件继续更新顶层（=当前轮）。
    const continueConversation = useCallback(async (versionId: string, question: string, model?: string) => {
        if (continuingVersions.current.has(versionId)) return;
        continuingVersions.current.add(versionId);
        try {
            // Accept the new round before Running opens a socket and reconciles server state.
            await continueLinsight(versionId, question, model);
            updateLinsight(versionId, (prev) => ({
                history: [
                    ...(prev.history || []),
                    {
                        // Stable id for React keys: position-derived but never reused
                        // (history is append-only, so the length is monotonic).
                        roundId: `${versionId}_round_${(prev.history || []).length}`,
                        question: prev.question,
                        tasks: prev.tasks || [],
                        sessionSteps: prev.sessionSteps || [],
                        output_result: prev.output_result,
                        file_list: prev.file_list || [],
                        // Carry the finished round's terminal state so ConversationRound
                        // can render its own stopped/error banner in history.
                        status: prev.status,
                        taskError: prev.taskError,
                        taskErrorInfo: prev.taskErrorInfo,
                    },
                ],
                question,
                tasks: [],
                sessionSteps: [],
                output_result: null,
                file_list: [],
                taskError: '',
                taskErrorInfo: undefined,
                execute_feedback: null,
                queueCount: 0,
                status: SopStatus.Running,
            }));
        } catch (e) {
            console.error('continueLinsight failed :>> ', e);
            updateLinsight(versionId, (prev) => ({
                status: SopStatus.Stoped, taskError: String(e), taskErrorInfo: undefined,
                output_result: prev.output_result?.error_message ? null : prev.output_result,
            }));
        } finally {
            continuingVersions.current.delete(versionId);
        }
    }, [updateLinsight]);

    const retryConversation = useRecoilCallback(({ snapshot }) => async (versionId: string, question: string) => {
        // Read at click time: the selector may have changed since this task failed.
        const selectedModel = await snapshot.getPromise(store.chatModel);
        await continueConversation(versionId, question, selectedModel.id > 0 ? String(selectedModel.id) : undefined);
    }, [continueConversation]);

    // 切换当前会话
    const switchSession = useCallback((versionId: string) => {
        setActiveSessionId(versionId);
    }, [setActiveSessionId]);

    // 切换会话，更新会话信息
    const switchAndUpdateLinsight = useCallback((versionId: string, update: any, customTask?: boolean) => {
        const linsight = getLinsight(versionId)
        if (linsight) return updateLinsight(versionId, { inputSop: false }); // 恢复用户未输入状态

        const { status, sop, execute_feedback, output_result, tasks, files, ...params } = update
        const newStatus = mapSessionVersionStatus(status, execute_feedback);
        const data = {
            ...params,
            output_result,
            execute_feedback,
            // summary: output_result?.answer,
            status: newStatus,
            files: files?.map(file => ({ ...file, file_name: decodeURIComponent(file.original_filename) })) || [],
            tasks: customTask ? tasks : buildTaskTree(tasks),
            taskError: 'failed' === status ? output_result?.error_message : '',
            taskErrorInfo: taskErrorInfoFromOutput(status, output_result),
            file_list: output_result?.final_files || [],
            sop: 'sop_generation_failed' === status ? '' : sop,
            sopError: 'sop_generation_failed' === status ? sop : '',
            queueCount: 0
        }

        createLinsight(versionId, data);
    }, [linsightMap])

    return {
        createLinsight,
        updateLinsight,
        getLinsight,
        switchSession,
        switchAndUpdateLinsight,
        continueConversation,
        retryConversation,
        reconcileLinsightFromServer,
        linsightMap
    };
};

// 获取当前活动会话的Hook
export const useActiveLinsight = () => {
    const activeSessionId = useRecoilValue(activeSessionIdState);
    const linsightMap = useRecoilValue(linsightMapState);

    return activeSessionId
        ? linsightMap.get(activeSessionId) || null
        : null;
};

/**
 * Map a backend session-version status (SessionVersionStatusEnum) to the
 * frontend SopStatus used by the store. Centralised so the reload path
 * (switchAndUpdateLinsight) agrees with the live WS pump on what "running" means.
 *
 * `not_started` means the session has been submitted + enqueued but the Linsight
 * worker has not picked it up yet (it flips to `in_progress` only on dequeue, in
 * task_exec._execute_workflow) — i.e. it is QUEUED. The F035 client has no manual
 * "start" affordance, so `not_started` is never a resting SOP state here; it must
 * map to Running so the queue polling stays enabled and <QueueCard> survives a
 * refresh / session switch (otherwise `running` is false and the 排队中 badge is
 * lost). A genuinely non-queued not_started degrades gracefully: queue-status
 * returns index 0, so no phantom card shows.
 *
 * `waiting_for_user_input` is a dedicated backend state (park-and-release HITL):
 * the run is parked on an ask_user interrupt, not finished. The live flow never
 * leaves SopStatus.Running while parked (the WS `user_input` event only changes
 * the task's status, not the session's), so on reload it MUST also map to Running
 * — otherwise `running` is false, the ClarifyCard / waiting input is gated off,
 * and the user sees no input prompt after a refresh.
 */
export function mapSessionVersionStatus(status: string, executeFeedback?: string | null): string {
    switch (status) {
        case 'sop_generation_failed':
            return SopStatus.SopGenerated;
        case 'not_started':
        case 'in_progress':
        case 'waiting_for_user_input':
            return SopStatus.Running;
        case 'completed':
            return executeFeedback ? SopStatus.FeedbackCompleted : SopStatus.completed;
        case 'terminated':
        case 'failed':
            return SopStatus.Stoped;
        default:
            return status; // unknown status passes through unchanged
    }
}

// Preserve task statuses: one pruned or stopped row must not hide later tasks.
function buildTaskTree(tasks) {
    const newTasks = tasks.map(task => {
        const taskTree = {
            id: task.id,
            // F035 deepagents tasks carry the title at task_data.name; tolerate a
            // flat name / legacy display_target too. MUST match the live WS
            // task_generate mapping (Websocket/index.tsx) or history-loaded turns
            // render blank task rows (structure present, names empty).
            name: task.name || task.task_data?.name || task.task_data?.display_target || '',
            status: task.status === 'waiting_for_user_input' ? 'user_input' : task.status,
            history: task.history || [],
            event_type: task.status === 'waiting_for_user_input' ? 'user_input' : '',
            call_reason: task.input_prompt || '',
            errorMsg: task.result?.answer || '',
            // Preserve task_data so splitSessionPseudoTask / PinnedTaskPanel can
            // recognize the session-global "执行准备" pseudo task (is_session_global)
            // on reload and lift its steps out, instead of rendering it as a task row.
            task_data: task.task_data,
            children: task.children?.map(child => {
                return {
                    id: child.id,
                    name: child.name || child.task_data?.name || child.task_data?.display_target || '',
                    status: child.status === 'waiting_for_user_input' ? 'user_input' : child.status,
                    history: child.history || [],
                    event_type: child.status === 'waiting_for_user_input' ? 'user_input' : '',
                    call_reason: '',
                    task_data: child.task_data
                }
            }) || []
        }

        return taskTree
    })
    return newTasks

}
