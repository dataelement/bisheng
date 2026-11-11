// @ts-strict-ignore
import { createBrowserNetworkFailure, taskFailureMetadata, type FailureInfo } from '~/utils/failureInfo';
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { userInputLinsightEvent, userStopLinsightEvent } from "~/api/linsight";
import { SopStatus } from "~/store/linsight";
import { useToastContext } from "~/Providers";
import { toggleNav } from "~/utils";
import { useLinsightManager } from "../useLinsightManager";
import { MockWebSocket } from "./mock";
import { observeModelRateLimitEvent } from "~/hooks/queries/endpoints/modelRateLimitPolling";
import { appendStepFrame } from '~/components/Linsight/Execution/stepFold';
import { closeCompletedTaskRows } from '../linsightCompletion';
const MOCK = false

// 每个会话单独分配一个 WebSocket实例
const connections: Record<string, WebSocket> = {};

export const useLinsightWebSocket = (versionId) => {
    const queryClient = useQueryClient();
    const { getLinsight, updateLinsight, reconcileLinsightFromServer } = useLinsightManager()
    const { showToast } = useToastContext();
    const maxRetryCountRef = useRef(5);
    const ownedSocketRef = useRef<WebSocket | MockWebSocket | null>(null);
    const [transportFailure, setTransportFailure] = useState<{ versionId: string; info: FailureInfo }>();
    const reportDisconnect = useCallback((id: string) => {
        setTransportFailure((previous) => previous?.versionId === id
            ? previous
            : { versionId: id, info: createBrowserNetworkFailure() });
    }, []);

    const linsight = getLinsight(versionId);
    const task = useMemo(() => {
        const linsight = getLinsight(versionId);
        return linsight
            ? { versionId, running: linsight.status === SopStatus.Running }
            : { versionId, running: false };
    }, [linsight?.status, versionId]);

    // 使用 ref 存储当前活跃版本 ID
    const activeVersionIdRef = useRef(versionId);
    // Live mirror of task.running, read inside the (stable, []-deps) connect
    // callback's onclose retry to avoid a stale closure and to gate reconnects.
    const runningRef = useRef(false);
    // Same reason: the connect callback must reach the CURRENT reconcile fn
    // without taking it as a dependency (that would rebuild connect and break
    // the self-referencing reconnect below).
    const reconcileRef = useRef(reconcileLinsightFromServer);

    // 同步最新活跃版本 ID
    useEffect(() => {
        activeVersionIdRef.current = versionId;
    }, [versionId]);

    useEffect(() => {
        runningRef.current = task.running;
    }, [task.running, versionId]);

    useEffect(() => {
        reconcileRef.current = reconcileLinsightFromServer;
    }, [reconcileLinsightFromServer]);


    const connect = useCallback((id: string, msg: any) => {
        // 清理可能存在的旧连接
        if (connections[id]) {
            connections[id].close();
        }

        function getWebSocketUrl(path) {
            // Use environment variable if available, otherwise fallback to current origin
            const baseUrl = window.location.origin;

            // Ensure proper protocol (convert http -> ws, https -> wss)
            let url;
            if (baseUrl.startsWith('https://')) {
                url = `wss://${baseUrl.replace('https://', '')}`;
            } else if (baseUrl.startsWith('http://')) {
                url = `ws://${baseUrl.replace('http://', '')}`;
            } else {
                // If no protocol specified, use current page's protocol
                const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
                url = `${protocol}${baseUrl}`;
            }

            // Ensure path starts with slash
            const normalizedPath = path.startsWith('/') ? path : `/${path}`;

            return `${url}${normalizedPath}`;
        }

        const websocket = MOCK ? new MockWebSocket(`xx`)
            : new WebSocket(getWebSocketUrl(`${__APP_ENV__.BASE_URL}/api/v1/linsight/workbench/task-message-stream?session_version_id=${id}`));
        connections[id] = websocket;
        ownedSocketRef.current = websocket;

        websocket.onopen = () => {
            if (connections[id] !== websocket || activeVersionIdRef.current !== id || !runningRef.current) return;
            setTransportFailure((previous) => previous?.versionId === id ? undefined : previous);
            console.log("WebSocket connection established!");
            // websocket.send(JSON.stringify(msg));
            // The run may have reached its end while we had no socket, and the
            // terminal event is destructively popped server-side — nobody will
            // resend it. Ask the DB what actually happened; a still-running
            // session is left to the stream (see reconcileLinsightFromServer).
            reconcileRef.current?.(id)?.catch((e) => {
                console.error(`Failed to reconcile session ${id} on open:`, e);
            });
        };

        websocket.onmessage = (event) => {
            const taskData = JSON.parse(event.data);
            /**
             * 生成一级任务list
             * 生成当前一级任务下的二级任务list
             * 更新生成的任务信息
             */
            switch (taskData.event_type) {
                case 'task_generate':
                    // 生成一级任务
                    updateLinsight(id, (prev) => {
                        // 创建顶级任务的浅拷贝
                        const updatedTasks = [...prev.tasks];

                        // 用于记录需要更新的父任务
                        const parentsToUpdate = new Map();

                        taskData.data.tasks.forEach(_task => {
                            if (_task.parent_task_id) {
                                // 处理子任务 - 收集到对应的父任务
                                const parentId = _task.parent_task_id;
                                if (!parentsToUpdate.has(parentId)) {
                                    parentsToUpdate.set(parentId, []);
                                }
                                parentsToUpdate.get(parentId).push({
                                    id: _task.id,
                                    // F035 deepagents tasks carry the title at task_data.name;
                                    // tolerate a flat name / legacy display_target too.
                                    name: _task.name ?? _task.task_data?.name ?? _task.task_data?.display_target ?? '',
                                    status: _task.status,
                                    history: [],
                                });
                            } else {
                                // 处理顶级任务 - 检查是否已存在
                                const exists = updatedTasks.some(t => t.id === _task.id);
                                if (!exists) {
                                    updatedTasks.push({
                                        id: _task.id,
                                        name: _task.name ?? _task.task_data?.name ?? _task.task_data?.display_target ?? '',
                                        status: _task.status,
                                        history: [],
                                        children: [],
                                    });
                                }
                            }
                        });

                        // 更新有子任务的父任务
                        parentsToUpdate.forEach((newChildren, parentId) => {
                            const parentIndex = updatedTasks.findIndex(t => t.id === parentId);
                            if (parentIndex === -1) return; // 父任务不存在

                            const parent = updatedTasks[parentIndex];
                            const existingChildIds = new Set(parent.children.map(c => c.id));

                            // 过滤掉已存在的子任务
                            const childrenToAdd = newChildren.filter(
                                child => !existingChildIds.has(child.id)
                            );

                            if (childrenToAdd.length > 0) {
                                // 创建新的父任务对象
                                updatedTasks[parentIndex] = {
                                    ...parent,
                                    children: [
                                        ...parent.children,
                                        ...childrenToAdd
                                    ]
                                };
                            }
                        });

                        // 返回全新的状态对象
                        return { tasks: updatedTasks };
                    });
                    break;
                case 'user_input': {
                    const { task_id, call_reason, params } = taskData.data;
                    updateLinsight(id, (prev) => {
                        let matched = false;
                        const newTasks = prev.tasks.map(task => {
                            if (task.id === task_id) {
                                matched = true;
                                // 更新父任务
                                return {
                                    ...task,
                                    status: taskData.event_type,
                                    event_type: taskData.event_type,
                                    params,
                                    call_reason,
                                    history: [...(task.history || []), {
                                        ...taskData.data
                                    }]
                                };
                            } else {
                                return {
                                    ...task,
                                    // status: taskData.event_type,
                                    children: (task.children || []).map(child => {
                                        if (child.id === task_id) {
                                            matched = true;
                                            // 更新子任务
                                            return {
                                                ...child, // 关键修复：使用 child 而不是 task
                                                status: taskData.event_type,
                                                event_type: taskData.event_type,
                                                params,
                                                call_reason,
                                                history: [...(child.history || []), {
                                                    ...taskData.data
                                                }]
                                            };
                                        }
                                        return child;
                                    })
                                };
                            }
                        });
                        if (matched) return { tasks: newTasks };
                        // F035 Track H: session-level pseudo task (task_id == session_version_id),
                        // e.g. pre-planning intent clarification — keep it at flow level
                        return {
                            sessionSteps: [...(prev.sessionSteps || []), { step_type: 'call_user_input', ...taskData.data }]
                        };
                    });
                    break;
                }
                case 'user_input_completed': {
                    // F035 Track H: stamp the answered clarify entries so the active
                    // ClarifyCard collapses into an intent-summary row (spec §2).
                    const completedId = taskData.data.id ?? taskData.data.task_id;
                    const answer = (taskData.data.history || [])
                        .filter((h: any) => h?.role === 'user')
                        .map((h: any) => h?.content)
                        .join('\n');
                    const markHistory = (history: any[]) => (history || []).map((h: any) =>
                        h?.step_type === 'call_user_input' && !h.is_completed
                            ? { ...h, is_completed: true, user_input: h.user_input || answer }
                            : h
                    );
                    updateLinsight(id, (prev) => ({
                        tasks: prev.tasks.map(task =>
                            task.id === completedId
                                ? { ...task, history: markHistory(task.history || []) }
                                : {
                                    ...task,
                                    children: (task.children || []).map(child =>
                                        child.id === completedId
                                            ? { ...child, history: markHistory(child.history || []) }
                                            : child
                                    )
                                }
                        ),
                        sessionSteps: (prev.sessionSteps || []).map((s: any) =>
                            s?.step_type === 'call_user_input' && s.task_id === completedId && !s.is_completed
                                ? { ...s, is_completed: true, user_input: s.user_input || answer }
                                : s
                        ),
                    }));
                }
                // falls through: shared status update below
                // eslint-disable-next-line no-fallthrough
                case 'task_start':
                case 'task_end':
                    updateLinsight(id, (prev) => {
                        const newStatus = taskData.data.status
                        const errorMsg = taskData.data.result?.answer
                        if (!taskData.data.parent_task_id) {
                            // 更新一级任务
                            const newTasks = prev.tasks.map(task =>
                                task.id === taskData.data.id
                                    ? { ...task, status: newStatus, errorMsg, event_type: taskData.event_type }
                                    : task
                            );
                            return { tasks: newTasks };
                        }

                        // 处理二级任务
                        const parentIndex = prev.tasks.findIndex(t => t.id === taskData.data.parent_task_id);
                        if (parentIndex === -1) return prev; // 父任务不存在

                        const parent = prev.tasks[parentIndex];
                        // const childIndex = parent.children.findIndex(c => c.id === taskData.data.id);

                        //  更新现有子任务
                        const newTasks = [...prev.tasks];
                        newTasks[parentIndex] = {
                            ...parent,
                            children: parent.children.map(child =>
                                child.id === taskData.data.id
                                    ? { ...child, status: newStatus, errorMsg: newStatus === 'failed' ? errorMsg : '', event_type: taskData.event_type }
                                    : child
                            )
                        };
                        return { tasks: newTasks };
                    });
                    break;
                case 'task_execute_step':
                    updateLinsight(id, (prev) => {
                        let matched = false;
                        const newTasks = prev.tasks.map(task => {
                            if (task.id === taskData.data.task_id) {
                                matched = true;
                                return {
                                    ...task,
                                    history: appendStepFrame(task.history, taskData.data)
                                };
                            } else {
                                const children = (task.children || []).map(child => {
                                    if (child.id !== taskData.data.task_id) return child;
                                    matched = true;
                                    return { ...child, history: appendStepFrame(child.history, taskData.data) };
                                });
                                return children.every((child, index) => child === task.children?.[index])
                                    ? task
                                    : { ...task, children };
                            }
                        });

                        if (matched) return { tasks: newTasks };
                        // F035 Track H: session-level steps (task_id == session_version_id,
                        // e.g. planning-stage tool calls) live at flow level
                        return {
                            sessionSteps: appendStepFrame(prev.sessionSteps, taskData.data)
                        };
                    });
                    break;
                case 'final_result':
                    updateLinsight(id, (prev) => ({
                        output_result: taskData.data.output_result,
                        // summary: taskData.data.output_result.answer,
                        file_list: taskData.data.output_result.final_files || [],
                        status: SopStatus.completed,
                        // A completed session must not retain live checklist spinners.
                        tasks: closeCompletedTaskRows(prev.tasks || []),
                    }))
                    toggleNav(true)
                    // Fetch authoritative task statuses after the backend sweep,
                    // including TASK_END updates this socket may have missed.
                    reconcileRef.current?.(id, taskData.data.output_result)?.catch((e) => {
                        console.error(`Failed to reconcile completed session ${id}:`, e);
                    });
                    break;
                case 'task_terminated':

                    updateLinsight(id, {
                        status: SopStatus.Stoped
                    })
                    break;
                case 'error_message':
                    console.error(taskData.data.error, id, activeVersionIdRef.current)
                    observeModelRateLimitEvent(queryClient, {
                        errorType: taskData.data.error_type,
                        modelId: taskData.data.model_id,
                        rateLimitState: taskData.data.rate_limit_state,
                    });
                    updateLinsight(id, {
                        taskError: taskData.data.error || ' ',
                        // Persist the failure on its own version, including in background.
                        taskErrorInfo: taskFailureMetadata(taskData.data),
                        status: SopStatus.Stoped
                    })
            }
        };

        websocket.onclose = () => {
            console.log(`WebSocket closed for session ${id}`);
            if (connections[id] === websocket) {
                delete connections[id];
                if (activeVersionIdRef.current !== id || !runningRef.current) return;
                reportDisconnect(id);
                if (navigator.onLine === false) return;
                if (maxRetryCountRef.current > 0) {
                    setTimeout(() => {
                        // Guard against zombie reconnects: only relink if this
                        // version is still the active one AND its task is still
                        // running. A completed / parked / navigated-away session
                        // must not be resurrected (the server closes it again,
                        // which would just burn through the retry budget).
                        if (activeVersionIdRef.current !== id || !runningRef.current || navigator.onLine === false) return;
                        if (connections[id] && connections[id].readyState <= WebSocket.OPEN) return;
                        maxRetryCountRef.current--;
                        connect(id, { type: 'relink' })
                    }, 1000);
                } else if (runningRef.current) {
                    // Retry budget spent while still running: there will be no
                    // further `onopen` to reconcile on, so take the last chance
                    // to adopt whatever state the server settled on. Without
                    // this, a backend restart mid-run strands the panel
                    // spinning until the user reloads.
                    reconcileRef.current?.(id)?.catch((e) => {
                        console.error(`Failed to reconcile session ${id} after retries:`, e);
                    });
                }
            } else {
            }
        };

        websocket.onerror = (error) => {
            console.error(`WebSocket error for session ${id}:`, error);
        };
    }, [queryClient, reportDisconnect])


    useEffect(() => {
        if (!task.running) return;

        const handleOffline = () => {
            reportDisconnect(task.versionId);
            connections[task.versionId]?.close();
        };
        const handleOnline = () => {
            if (connections[task.versionId] && connections[task.versionId].readyState <= WebSocket.OPEN) return;
            maxRetryCountRef.current = 3;
            connect(task.versionId, { type: 'relink' });
        };
        window.addEventListener('offline', handleOffline);
        window.addEventListener('online', handleOnline);
        if (navigator.onLine === false) handleOffline();
        else handleOnline();
        return () => {
            window.removeEventListener('offline', handleOffline);
            window.removeEventListener('online', handleOnline);
            runningRef.current = false;
            const socket = ownedSocketRef.current;
            ownedSocketRef.current = null;
            if (socket && connections[task.versionId] === socket) {
                // Retire this consumer before close fires. A remount must own a
                // fresh socket instead of inheriting callbacks from a dead hook.
                delete connections[task.versionId];
                socket.close();
            }
        };
    }, [task, connect, reportDisconnect])

    const stop = useCallback(() => {
        if (MOCK) {
            const ws = connections[versionId];
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'stop' }));
            }
        } else {
            userStopLinsightEvent(versionId)
            updateLinsight(versionId, (prev) => ({
                ...prev,
                status: SopStatus.Stoped,
                tasks: prev.tasks.map(task => ({
                    ...task,
                    status: task.status === "in_progress" ? "terminated" : task.status,
                    children: task.children
                        ? task.children.map(child => ({
                            ...child,
                            status: child.status === "in_progress" ? "terminated" : child.status,
                        }))
                        : [],
                })),
            }));
        }
        toggleNav(true)
    }, [versionId])

    const sendInput = useCallback(({ task_id, user_input, files }) => {
        if (MOCK) {
            const ws = connections[versionId];
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ user_input }));
            }
        } else {
            userInputLinsightEvent(versionId, task_id, user_input, files.map((file) => file.result))
            // update is_completed user_input files
            // @ts-ignore
            updateLinsight(versionId, (prev) => ({
                ...prev,
                // F035 Track H: optimistic stamp for session-level clarify entries too
                sessionSteps: (prev.sessionSteps || []).map((s: any) =>
                    s?.step_type === 'call_user_input' && !s.is_completed
                        ? { ...s, is_completed: true, user_input: s.user_input || user_input, files: s.files || files }
                        : s
                ),
                // Only stamp the answered task's OPEN clarify entry — mirrors the
                // WS `user_input_completed` handler. The previous version blanket-
                // marked every history entry of every task is_completed AND forced
                // the answered task to "success", but answering a clarify RESUMES
                // execution (≠ completion) and must not touch sibling tasks / steps.
                // Status is left to the WS stream.
                tasks: prev.tasks.map(task => {
                    const stampOpenClarify = (h: any) =>
                        h?.step_type === 'call_user_input' && !h.is_completed
                            ? { ...h, is_completed: true, user_input: h.user_input || user_input, files: h.files || files }
                            : h;
                    if (task.id === task_id) {
                        return { ...task, history: task.history?.map(stampOpenClarify) };
                    }
                    return {
                        ...task,
                        children: (task.children || []).map(child =>
                            child.id === task_id
                                ? { ...child, history: child.history?.map(stampOpenClarify) }
                                : child
                        ),
                    };
                }),
            }));
        }
    }, [versionId]);

    return {
        stop,
        sendInput,
        // Transport failure is ephemeral: the worker may still be running.
        // Never write it into taskError/status or offer a duplicate task retry.
        networkFailure: task.running && transportFailure?.versionId === versionId
            ? transportFailure.info
            : undefined,
    };
};
