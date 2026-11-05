// @ts-strict-ignore
import { useLocalize } from '~/hooks';
import { taskFailureMetadata } from '~/utils/failureInfo';
// src/hooks/useLinsightManager.ts
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
    useRecoilCallback,
    useRecoilState,
    useRecoilValue,
    useSetRecoilState
} from 'recoil';
import { SSE } from 'sse.js';
import { continueLinsight, getLinsightSessionVersionList, getLinsightTaskList, startLinsight } from '~/api/linsight';
import { ConversationData, QueryKeys } from '~/types/chat';
import { useToastContext } from '~/Providers';
import store from '~/store';
import { activeSessionIdState, LinsightInfo, linsightMapState, SopStatus, submissionState, SubmissionState } from '~/store/linsight';
import {
    addConversation,
    formatTime,
    toggleNav
} from '~/utils';
import { getContinueFailureUpdate } from './linsightContinueHelpers';
import { convertTools, buildTaskTree, mapSessionVersionStatus } from './linsightSessionProjection';
import { resolveLinsightSubmitFailure, type PendingSubmitFailure } from './linsightSubmitFailure';
export { mapSessionVersionStatus } from './linsightSessionProjection';


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

    // 创建新会话信息
    const createLinsight = useCallback((versionId: string, initialData: Omit<LinsightInfo, 'id'>, activate = true) => {
        const newLinsight: LinsightInfo = {
            id: versionId,
            ...initialData
        };

        setLinsightMap(prevMap => {
            const newMap = new Map(prevMap);
            newMap.set(versionId, newLinsight);
            return newMap;
        });

        if (activate) setActiveSessionId(versionId);
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

    /**
     * Re-sync one session version from the server and adopt a TERMINAL state.
     *
     * The task-message-stream WS is the only carrier of terminal events
     * (final_result / task_terminated / error_message), and the backend hands
     * them out with a destructive BLPOP: a socket that dies between the pop and
     * the send takes the event with it. The reconnect that follows then blocks
     * on an empty queue forever, so a run that finished inside the disconnect
     * window leaves the panel spinning on its last live snapshot (and its task
     * progress frozen mid-count) until the user reloads the page.
     *
     * Reconciling against the DB — the authority — closes that window. It runs
     * on every WS open rather than only on reconnects, because the same event
     * can also be swallowed by a competing consumer of the shared queue (a
     * second tab on the same session, or a previous connection's server-side
     * coroutine still parked in BLPOP), which a first connection is no more
     * immune to than a relink.
     *
     * Deliberately one-way: server state is adopted ONLY once the run has
     * reached a terminal status. A still-running session is left untouched —
     * the snapshot is fetched asynchronously and would otherwise clobber live
     * WS events that landed while it was in flight. Terminal states take no
     * further events, so there is nothing left to lose.
     *
     * Reads the store through a Recoil snapshot: the caller lives inside the
     * WS pump's `[]`-deps connect callback, where a captured `getLinsight`
     * would be a first-render closure.
     *
     * @returns true if a terminal state was adopted, false if left alone.
     */
    const reconcileLinsightFromServer = useRecoilCallback(({ snapshot }) => async (
        versionId: string,
        expectedCompletedOutput?: LinsightInfo['output_result'],
        adoptActive = false,
    ) => {
        const map = await snapshot.getPromise(linsightMapState);
        const current = map.get(versionId);
        // No session_id ⇒ nothing to query by (entry not hydrated yet).
        if (!current?.session_id) return false;

        const versions = await getLinsightSessionVersionList(current.session_id, '');
        const item = (versions || []).find((v) => String(v.id) === String(versionId));
        if (!item) return false;
        const terminal = TERMINAL_SESSION_STATUSES.has(item.status);
        if (!terminal) {
            if (!adoptActive || !['not_started', 'in_progress', 'waiting_for_user_input'].includes(item.status)) return false;
            updateLinsight(versionId, (latest) => {
                // A late active snapshot must never revive a terminal live event.
                if ([SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(latest.status)) return {};
                return { status: mapSessionVersionStatus(item.status, item.execute_feedback) };
            });
            return true;
        }

        // Same shape the reload path builds (switchAndUpdateLinsight), so a
        // reconciled panel is indistinguishable from a freshly loaded one.
        const tasks = await getLinsightTaskList(versionId, item, '');
        updateLinsight(versionId, (latest) => {
            // A follow-up reuses the version id but clears its previous output.
            // Reject a completion fetch that arrived after that next round began.
            if (expectedCompletedOutput !== undefined && (
                latest.status !== SopStatus.completed || latest.output_result !== expectedCompletedOutput
            )) return {};
            return {
                status: mapSessionVersionStatus(item.status, item.execute_feedback),
                output_result: item.output_result,
                execute_feedback: item.execute_feedback,
                tasks: buildTaskTree(tasks),
                file_list: item.output_result?.final_files || [],
                taskError: 'failed' === item.status ? item.output_result?.error_message || ' ' : '',
                taskErrorInfo: 'failed' === item.status ? taskFailureMetadata(item.output_result) : undefined,
                // Carry the persisted task ChatMessage id + verdict, exactly as the
                // live final_result handler does, so like/dislike targets the right
                // row instead of a streaming placeholder.
                ...(item.message_id != null ? { message_id: item.message_id, liked: item.liked } : {}),
                queueCount: 0,
            };
        });
        return true;
    }, [updateLinsight]);

    // F035 多轮对话：在已完成的同一会话里追加新一轮。
    // 复用同一 session_version (versionId) + 同一 agent thread，后端保留全部上下文；
    // 前端把当前轮快照进 history，再清空顶层字段开新轮，WS 事件继续更新顶层（=当前轮）。
    const continueConversation = useCallback(async (
        versionId: string,
        question: string,
        modelId?: string | number,
    ): Promise<boolean> => {
        const originalLinsight = linsightMap.get(versionId);
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
            status: SopStatus.Running,
        }));
        try {
            await continueLinsight(versionId, question, modelId);
            return true;
        } catch (e) {
            console.error('continueLinsight failed :>> ', e);
            // Switching is one atomic user action: a rejected switch restores
            // the full failed round. Plain retry keeps its legacy failure state.
            updateLinsight(versionId, getContinueFailureUpdate(originalLinsight, modelId, e));
            return false;
        }
    }, [linsightMap, updateLinsight]);

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
            taskError: 'failed' === status ? output_result?.error_message || ' ' : '',
            taskErrorInfo: 'failed' === status ? taskFailureMetadata(output_result) : undefined,
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


export const useLinsightSessionManager = (versionId: string) => {
    const linsightSubmission = useRecoilValue(submissionState(versionId));
    // 添加或更新会话状态
    const setLinsightSubmission = useRecoilCallback(({ set }) =>
        (versionId: string, state: SubmissionState) => {
            set(submissionState(versionId), state);
        },
        []
    );

    // 清空指定会话状态
    const clearLinsightSubmission = useRecoilCallback(({ set }) =>
        (versionId: string) => {
            set(submissionState(versionId), null);
        },
        []
    );

    return {
        linsightSubmission,
        setLinsightSubmission,
        clearLinsightSubmission
    };
};


/**
 * F035 Track H (P5): submit pipeline for a new task-mode session.
 * Watches submissionState(versionId) and drives the workbench submit SSE,
 * then starts execution directly (no SOP generation step anymore).
 * sessionId规则说明: 新建会话 [new]
 */
export const useLinsightSubmit = (versionId, setVersionId, setVersions) => {
    const localize = useLocalize();
    const [loading, setLoading] = useState(false); // 多会话共用
    // F035: a new round always submits under the 'new' key (the next version has
    // no id yet). Watch 'new' fixed — NOT `versionId` — otherwise follow-up rounds
    // after the first one (versionId is a real id by then) never fire and
    // "continue conversation" looks dead.
    const { linsightSubmission, clearLinsightSubmission } = useLinsightSessionManager('new')
    const { createLinsight, updateLinsight, reconcileLinsightFromServer } = useLinsightManager()
    const queryClient = useQueryClient();
    const { showToast } = useToastContext();
    const [error, setError] = useState(false);
    const [pendingSubmitFailure, setPendingSubmitFailure] = useState<PendingSubmitFailure>();
    const pendingFailureOwnerRef = useRef<{ versionId: string; path: string }>();
    const submitSequenceRef = useRef(0);
    const { setConversation } = store.useCreateConversationAtom(0);
    // 使用 ref 存储当前活跃版本 ID
    const activeVersionIdRef = useRef(versionId);
    // 同步最新活跃版本 ID
    useEffect(() => {
        activeVersionIdRef.current = versionId;
    }, [versionId]);

    // 切换非新建会话不展示loading
    useEffect(() => {
        if (versionId !== 'new') setTimeout(() => {
            setLoading(false)
        }, 2000);
    }, [versionId])

    useEffect(() => {
        if (linsightSubmission) {
            setPendingSubmitFailure(undefined);
            pendingFailureOwnerRef.current = undefined;
            setError(false);
            console.log('linsightSubmission :>> ', linsightSubmission);

            // 新建会话获取详情
            if (linsightSubmission.isNew) {
                const submitSequence = ++submitSequenceRef.current;
                const submitFromVersion = activeVersionIdRef.current;
                let submitFromPath = window.location.pathname;
                setLoading(true)
                toggleNav(false)

                const { org_knowledge_enabled, personal_knowledge_enabled, tools } = convertTools(linsightSubmission.tools)
                const payload = {
                    question: linsightSubmission.question,
                    org_knowledge_enabled,
                    personal_knowledge_enabled,
                    files: linsightSubmission.files,
                    tools,
                    // F035: per-task model selection; null lets the backend fall back
                    // to the tenant's linsight default model
                    model: linsightSubmission.model || null,
                    // F035 Track H: user-picked skill names (forward-compatible —
                    // the submit schema does not consume this field yet)
                    skills: linsightSubmission.skills || [],
                    // F035: continue an existing session (follow-up round) so the
                    // backend appends a version instead of creating a new 会话.
                    session_id: linsightSubmission.sessionId || null,
                }

                const sse = new SSE(`${__APP_ENV__.BASE_URL}/api/v1/linsight/workbench/submit`, {
                    payload: JSON.stringify(payload),
                    headers: {
                        'Content-Type': 'application/json'
                    },
                });

                let versionId = ''
                const isCurrentSubmission = () => submitSequence === submitSequenceRef.current
                    && window.location.pathname === submitFromPath
                    && (activeVersionIdRef.current === submitFromVersion || activeVersionIdRef.current === versionId);
                sse.addEventListener('linsight_workbench_submit', (e: MessageEvent) => {
                    const data = JSON.parse(e.data);
                    const { linsight_session_version, message_session } = data;

                    const showSubmission = isCurrentSubmission();
                    versionId = linsight_session_version.id
                    if (showSubmission) {
                        setVersionId(versionId)
                        setVersions((prevVersions) => [{
                            id: versionId,
                            name: formatTime(linsight_session_version.version, true)
                        }, ...prevVersions])
                        window.history.replaceState({}, '', `${__APP_ENV__.BASE_URL}/linsight/${linsight_session_version.session_id}`);
                        submitFromPath = window.location.pathname;
                    }

                    createLinsight(versionId, {
                        status: SopStatus.SopGenerating, //linsight_session_version.status,
                        tools: tools,
                        files: linsight_session_version.files?.map(file => ({ ...file, file_name: decodeURIComponent(file.original_filename) })) || [],
                        user_id: linsight_session_version.user_id,
                        question: linsightSubmission.question,
                        org_knowledge_enabled,
                        personal_knowledge_enabled,
                        sop: '',
                        execute_feedback: null,
                        version: versionId,
                        create_time: linsight_session_version.create_time.rep,
                        session_id: linsight_session_version.session_id,
                        output_result: null,
                        score: null,
                        has_reexecute: false,
                        update_time: linsight_session_version.update_time,
                        title: message_session.flow_name,
                        tasks: [],
                        summary: '',
                        file_list: [],
                        inputSop: false,
                        sopError: '',
                        taskError: '',
                        queueCount: 0
                    }, showSubmission)
                })

                sse.addEventListener('linsight_workbench_title_generate', (e: MessageEvent) => {
                    const data = JSON.parse(e.data);
                    // 新建会话
                    queryClient.setQueryData<ConversationData>([QueryKeys.allConversations], (convoData) => {
                        if (!convoData) {
                            return convoData;
                        }
                        updateLinsight(versionId, {
                            title: data.task_title
                        })
                        if (isCurrentSubmission()) setConversation((prevState: any) => {
                            return {
                                ...prevState,
                                conversationId: data.chat_id
                            }
                        })
                        return addConversation(convoData, {
                            conversationId: data.chat_id,
                            createdAt: "",
                            endpoint: null,
                            endpointType: null,
                            model: "",
                            flowType: 20,
                            title: data.task_title,
                            tools: [],
                            updatedAt: ""
                        });
                    });
                    // F035 deepagents: no SOP generation step anymore — kick off
                    // execution right after the session is created; the WS stream
                    // (task-message-stream) takes over from here.
                    startLinsight(versionId).then(() => {
                        updateLinsight(versionId, (latest) =>
                            [SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(latest.status)
                                ? {} : { status: SopStatus.Running })
                        if (isCurrentSubmission()) setLoading(false)
                    }).catch(async (err) => {
                        console.error('start-execute failed :>> ', err);
                        const { failure, metadata, businessMessage } = resolveLinsightSubmitFailure(err, localize, 'com_linsight.task_start_failed');
                        if (!businessMessage) {
                            try {
                                if (await reconcileLinsightFromServer(versionId, undefined, true)) {
                                    if (isCurrentSubmission()) setLoading(false);
                                    return;
                                }
                            } catch (reconcileError) {
                                console.error('Failed to reconcile task start:', reconcileError);
                            }
                        }
                        if (isCurrentSubmission()) {
                            showToast({ message: failure.message, status: 'warning' });
                            setError(true)
                            setLoading(false)
                            toggleNav(true)
                        }
                        updateLinsight(versionId, (latest) => {
                            if ([SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(latest.status)) return {};
                            return {
                                taskError: failure.message,
                                taskErrorInfo: metadata,
                                ...(businessMessage ? { status: SopStatus.Stoped } : {}),
                            };
                        })
                    })
                })

                sse.addEventListener('open', () => {
                    console.log('connection is opened');
                });

                sse.addEventListener('error', async (e: MessageEvent) => {
                    console.error('object :>> ', e);
                    let payload: unknown;
                    try { payload = JSON.parse(e.data); } catch { payload = {}; }
                    const { failure, metadata, businessMessage } = resolveLinsightSubmitFailure(payload, localize, 'com_linsight.task_submit_failed');
                    if (versionId && !businessMessage) {
                        try {
                            if (await reconcileLinsightFromServer(versionId, undefined, true)) {
                                if (isCurrentSubmission()) setLoading(false);
                                return;
                            }
                        } catch (reconcileError) {
                            console.error('Failed to reconcile task submit:', reconcileError);
                        }
                    }
                    if (!versionId && submitSequence === submitSequenceRef.current) {
                        pendingFailureOwnerRef.current = { versionId: submitFromVersion, path: submitFromPath };
                        setPendingSubmitFailure(failure);
                    }
                    if (isCurrentSubmission()) {
                        showToast({
                            message: failure.message,
                            status: 'warning',
                        });
                        setError(true)
                        setLoading(false)
                        toggleNav(true)
                    }
                    if (versionId) updateLinsight(versionId, (latest) => {
                        if ([SopStatus.completed, SopStatus.FeedbackCompleted, SopStatus.Stoped].includes(latest.status)) return {};
                        return {
                            taskError: failure.message,
                            taskErrorInfo: metadata,
                            sopError: '',
                            ...(businessMessage ? { status: SopStatus.Stoped } : {}),
                        };
                    })
                })
                sse.stream();
            }
            // F035 Track H (P5): the legacy non-isNew branch (re-execute via the
            // removed generate-sop SSE) is gone together with SOPEditor/TaskFlow.

            if (!linsightSubmission.isNew) updateLinsight(versionId, {
                status: SopStatus.SopGenerating,
                taskError: '',
                sopError: '',
                sop: ''
            })
            clearLinsightSubmission('new')
        }
    }, [linsightSubmission])

    const visiblePendingFailure = pendingFailureOwnerRef.current?.versionId === versionId
        && pendingFailureOwnerRef.current?.path === window.location.pathname ? pendingSubmitFailure : undefined;
    return [loading, error, visiblePendingFailure] as const
}



// 工具转换数据结构  筛选 -> sop二级列表
