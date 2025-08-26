import { useCallback, useEffect, useMemo, useRef } from "react";
import { userInputLinsightEvent, userStopLinsightEvent } from "~/api/linsight";
import { SopStatus } from "~/components/Sop/SOPEditor";
import { useToastContext } from "~/Providers";
import { toggleNav } from "~/utils";
import { useLinsightManager } from "../useLinsightManager";
import { MockWebSocket } from "./mock";
const MOCK = false

// 每个会话单独分配一个 WebSocket实例
const connections: Record<string, WebSocket> = {};

export const useLinsightWebSocket = (versionId) => {
    const { getLinsight, updateLinsight } = useLinsightManager()
    const { showToast } = useToastContext();
    const maxRetryCountRef = useRef(5);

    const linsight = getLinsight(versionId);
    const task = useMemo(() => {
        const linsight = getLinsight(versionId);
        return linsight
            ? { versionId, running: linsight.status === SopStatus.Running }
            : { versionId, running: false };
    }, [linsight?.status, versionId]);

    // 使用 ref 存储当前活跃版本 ID
    const activeVersionIdRef = useRef(versionId);

    // 同步最新活跃版本 ID
    useEffect(() => {
        activeVersionIdRef.current = versionId;
    }, [versionId]);


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

        websocket.onopen = () => {
            console.log("WebSocket connection established!");
            // websocket.send(JSON.stringify(msg));
        };

        websocket.onmessage = (event) => {
            const taskData = JSON.parse(event.data);
            console.log('ws data :>> ', taskData);

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
                                    name: _task.task_data.display_target,
                                    status: _task.status,
                                    history: [],
                                });
                            } else {
                                // 处理顶级任务 - 检查是否已存在
                                const exists = updatedTasks.some(t => t.id === _task.id);
                                if (!exists) {
                                    updatedTasks.push({
                                        id: _task.id,
                                        name: _task.task_data.display_target,
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
                case 'user_input':
                    const { task_id, call_reason } = taskData.data;
                    updateLinsight(id, (prev) => {
                        const newTasks = prev.tasks.map(task => {
                            if (task.id === task_id) {
                                // 更新父任务
                                return {
                                    ...task,
                                    status: taskData.event_type,
                                    event_type: taskData.event_type,
                                    call_reason
                                };
                            } else {
                                return {
                                    ...task,
                                    // status: taskData.event_type,
                                    children: task.children.map(child => {
                                        if (child.id === task_id) {
                                            // 更新子任务
                                            return {
                                                ...child, // 关键修复：使用 child 而不是 task
                                                status: taskData.event_type,
                                                event_type: taskData.event_type,
                                                call_reason
                                            };
                                        }
                                        return child;
                                    })
                                };
                            }
                        });
                        return { tasks: newTasks };
                    });
                    break;
                case 'user_input_completed':
                case 'task_start':
                case 'task_end':
                    updateLinsight(id, (prev) => {
                        const newStatus = taskData.data.status
                        const errorMsg = newStatus === 'failed' ? taskData.data.result.answer : ''
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
                                    ? { ...child, status: newStatus, errorMsg, event_type: taskData.event_type }
                                    : child
                            )
                        };
                        return { tasks: newTasks };
                    });
                    break;
                case 'task_execute_step':
                    updateLinsight(id, (prev) => {
                        const newTasks = prev.tasks.map(task => {
                            if (task.id === taskData.data.task_id) {
                                return {
                                    ...task,
                                    history: [...task.history, taskData.data]
                                };
                            } else {
                                return {
                                    ...task,
                                    children: task.children.map(child => {
                                        if (child.id === taskData.data.task_id) {
                                            return {
                                                ...child,
                                                history: [...child.history, taskData.data]
                                            };
                                        }
                                        return child;
                                    })
                                };
                            }
                        });

                        return {
                            tasks: newTasks
                        };
                    });
                    break;
                case 'final_result':
                    updateLinsight(id, {
                        output_result: taskData.data.output_result,
                        // summary: taskData.data.output_result.answer,
                        file_list: taskData.data.output_result.final_files || [],
                        status: SopStatus.completed
                    })
                    toggleNav(true)
                    break;
                case 'task_terminated':

                    updateLinsight(id, {
                        status: SopStatus.Stoped
                    })
                    break;
                case 'error_message':
                    console.error(taskData.data.error, id, activeVersionIdRef.current)
                    if (id === activeVersionIdRef.current) {
                        updateLinsight(id, {
                            taskError: taskData.data.error,
                            status: SopStatus.Stoped
                        })
                        // showToast({ message: taskData.data.error, status: 'error' });
                    }
            }
        };

        websocket.onclose = () => {
            console.log(`WebSocket closed for session ${id}`);
            if (connections[id] === websocket) {
                delete connections[id];
                if (maxRetryCountRef.current > 0) {
                    setTimeout(() => {
                        connect(id, { type: 'relink' })
                        maxRetryCountRef.current--;
                    }, 1000);
                }
            } else {
            }
        };

        websocket.onerror = (error) => {
            console.error(`WebSocket error for session ${id}:`, error);
        };
    }, [])


    useEffect(() => {
        if (!task.running) return;

        // 当没有连接或连接已关闭时创建新连接
        if (!connections[task.versionId] ||
            connections[task.versionId].readyState !== WebSocket.OPEN) {
            connect(task.versionId, { type: 'init' });
            maxRetryCountRef.current = 3;
        }
    }, [task])

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

    const sendInput = useCallback(({ task_id, user_input }) => {
        if (MOCK) {
            const ws = connections[versionId];
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ user_input }));
            }
        } else {
            userInputLinsightEvent(versionId, task_id, user_input)
        }
    }, [versionId]);

    return { stop, sendInput };
};

