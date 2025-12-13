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
import { SopStatus } from '~/components/Sop/SOPEditor';
import { ConversationData, QueryKeys } from '~/data-provider/data-provider/src';
import { useToastContext } from '~/Providers';
import store from '~/store';
import { activeSessionIdState, LinsightInfo, linsightMapState, submissionState, SubmissionState } from '~/store/linsight';
import {
    addConversation,
    formatTime,
    toggleNav
} from '~/utils';


export const useLinsightManager = () => {
    const [linsightMap, setLinsightMap] = useRecoilState(linsightMapState);
    const setActiveSessionId = useSetRecoilState(activeSessionIdState);

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

    // 切换当前会话
    const switchSession = useCallback((versionId: string) => {
        setActiveSessionId(versionId);
    }, [setActiveSessionId]);

    // 切换会话，更新会话信息
    const switchAndUpdateLinsight = useCallback((versionId: string, update: any, customTask?: boolean) => {
        const linsight = getLinsight(versionId)
        if (linsight) return updateLinsight(versionId, { inputSop: false }); // 恢复用户未输入状态

        const { status, sop, execute_feedback, output_result, tasks, files, ...params } = update
        let newStatus = ''
        switch (status) {
            case 'not_started':
            case 'sop_generation_failed':
                newStatus = SopStatus.SopGenerated;
                break;
            case 'in_progress':
                newStatus = SopStatus.Running;
                break;
            case 'completed':
                newStatus = execute_feedback ? SopStatus.FeedbackCompleted : SopStatus.completed;
                break;
            case 'terminated':
            case 'failed':
                newStatus = SopStatus.Stoped;
                break;
            default:
                newStatus = status; // 或设置默认值
                break;
        }
        const data = {
            ...params,
            output_result,
            execute_feedback,
            // summary: output_result?.answer,
            status: newStatus,
            files: files?.map(file => ({ ...file, file_name: decodeURIComponent(file.original_filename) })) || [],
            tasks: customTask ? tasks : buildTaskTree(tasks),
            taskError: 'failed' === status ? output_result?.error_message : '',
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
 * 生成sop
 * @param versionId 
 * sessionId规则说明
 * 新建会话 [new]
 * 重新执行 [会话id-版本id]
 */
export const useGenerateSop = (versionId, setVersionId, setVersions) => {
    const [loading, setLoading] = useState(false); // 多会话共用
    const { linsightSubmission, clearLinsightSubmission } = useLinsightSessionManager(versionId)
    const { createLinsight, updateLinsight } = useLinsightManager()
    const queryClient = useQueryClient();
    const { showToast } = useToastContext();
    const [error, setError] = useState(false);
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

    // 生成会话
    const generateSop = (_versionId, sameSopId, linsightSubmission?: any) => {
        const payload = {
            linsight_session_version_id: _versionId,
            feedback_content: linsightSubmission?.feedback,
            reexecute: false
        }
        if (linsightSubmission) {
            payload.previous_session_version_id = linsightSubmission.prevVersionId
            payload.reexecute = true
        }

        if (sameSopId) {
            payload.sop_id = sameSopId
        }

        const sse = new SSE(`${__APP_ENV__.BASE_URL}/api/v1/linsight/workbench/generate-sop`, {
            payload: JSON.stringify(payload),
            headers: {
                'Content-Type': 'application/json'
            },
        });

        let content = ''
        sse.addEventListener('generate_sop_content', (e: MessageEvent) => {
            const data = JSON.parse(e.data);
            content += data.content
            updateLinsight(_versionId, {
                sopError: '',
                sop: content.replace(/^---/, '').replace('```markdown\n', '```'),
                inputSop: false
            })
        })

        sse.addEventListener('sop_generate_complete', (e: MessageEvent) => {
            // const data = JSON.parse(e.data);
            updateLinsight(_versionId, {
                status: SopStatus.SopGenerated,
            })
        })

        sse.addEventListener('search_sop_error', (e: MessageEvent) => {
            // const data = JSON.parse(e.data);
            showToast({
                message: e.data,
                status: 'warning',
            });
            updateLinsight(_versionId, {
                sopError: e.data
            })
        })

        sse.addEventListener('open', () => {
            console.log('connection is opened');
            // setLoading(false)
        });

        sse.addEventListener('error', async (e: MessageEvent) => {
            console.error('object :>> ', e);
            if (_versionId === activeVersionIdRef.current) { // 只有当前活跃会话才展示错误
                showToast({
                    message: 'SOP 生成失败，请联系管理员检查灵思任务执行模型状态',
                    status: 'error',
                });
                setError(true)
                setLoading(false)
            }
            updateLinsight(_versionId, {
                sopError: e.data,
                status: SopStatus.SopGenerated,
            })
        })
        sse.stream();
    }


    useEffect(() => {
        if (linsightSubmission) {
            console.log('linsightSubmission :>> ', linsightSubmission);

            // 新建会话获取详情
            if (linsightSubmission.isNew) {
                setLoading(true)
                toggleNav(false)

                const { org_knowledge_enabled, personal_knowledge_enabled, tools } = convertTools(linsightSubmission.tools)
                const payload = {
                    question: linsightSubmission.question,
                    org_knowledge_enabled,
                    personal_knowledge_enabled,
                    files: linsightSubmission.files,
                    tools,
                }

                const sse = new SSE(`${__APP_ENV__.BASE_URL}/api/v1/linsight/workbench/submit`, {
                    payload: JSON.stringify(payload),
                    headers: {
                        'Content-Type': 'application/json'
                    },
                });

                let versionId = ''
                sse.addEventListener('linsight_workbench_submit', (e: MessageEvent) => {
                    const data = JSON.parse(e.data);
                    const { linsight_session_version, message_session } = data;

                    versionId = linsight_session_version.id
                    setVersionId(versionId)
                    setVersions((prevVersions) => [{
                        id: versionId,
                        name: formatTime(linsight_session_version.version, true)
                    }, ...prevVersions])

                    // replaceUrl
                    window.history.replaceState({}, '', `${__APP_ENV__.BASE_URL}/linsight/${linsight_session_version.session_id}`);

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
                    })
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
                        setConversation((prevState: any) => {
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
                    // 开启生成sop
                    generateSop(versionId, linsightSubmission.sameSopId)
                })

                sse.addEventListener('open', () => {
                    console.log('connection is opened');
                });

                sse.addEventListener('error', async (e: MessageEvent) => {
                    console.error('object :>> ', e);
                    if (versionId === activeVersionIdRef.current) { // 只有当前活跃会话才展示错误
                        showToast({
                            message: 'SOP 生成失败，请联系管理员检查灵思任务执行模型状态',
                            status: 'error',
                        });
                        setError(true)
                        setLoading(false)
                    }
                    updateLinsight(versionId, {
                        sopError: e.data,
                        status: SopStatus.SopGenerated,
                    })
                })
                sse.stream();
            } else {
                generateSop(versionId, linsightSubmission.sameSopId, linsightSubmission)
            }

            updateLinsight(versionId, {
                status: SopStatus.SopGenerating,
                taskError: '',
                sopError: '',
                sop: ''
            })
            clearLinsightSubmission(versionId)
            setError(false)
        }
    }, [linsightSubmission])

    return [loading, error]
}



// 工具转换数据结构  筛选 -> sop二级列表
const convertTools = (tools) => {
    let org_knowledge_enabled = false
    let personal_knowledge_enabled = false

    const sopTools: any = []
    tools.forEach(tool => {
        if (tool.checked && tool.id === 'pro_knowledge') {
            org_knowledge_enabled = true
        } else if (tool.checked && tool.id === 'knowledge') {
            personal_knowledge_enabled = true
        } else if (tool.checked) {
            const { id, name, is_preset, description, children } = tool.data
            sopTools.push({
                id,
                name,
                is_preset,
                description,
                children: children.map(api => {
                    return {
                        id: api.id,
                        name: api.name,
                        tool_key: api.tool_key,
                        desc: api.desc
                    }
                })
            })
        }
    });

    return {
        org_knowledge_enabled,
        personal_knowledge_enabled,
        tools: sopTools
    }
}


function buildTaskTree(tasks) {
    let hasTerminated = false
    const newTasks = tasks.map(task => {
        const taskTree = {
            id: task.id,
            name: task.task_data?.display_target || '',
            status: hasTerminated ? 'not_started' : task.status === 'waiting_for_user_input' ? 'user_input' : task.status,
            history: task.history || [],
            event_type: task.status === 'waiting_for_user_input' ? 'user_input' : '',
            call_reason: task.input_prompt || '',
            errorMsg: task.result?.answer || '',
            children: task.children?.map(child => {
                return {
                    id: child.id,
                    name: child.task_data?.display_target || '',
                    status: child.status === 'waiting_for_user_input' ? 'user_input' : child.status,
                    history: child.history || [],
                    event_type: child.status === 'waiting_for_user_input' ? 'user_input' : '',
                    call_reason: ''
                }
            }) || []
        }

        // 处理终止后的任务全部为not_started（隐藏）
        if (['terminated', 'failed'].includes(task.status)) {
            hasTerminated = true
        }

        return taskTree
    })
    return newTasks

    // 创建任务ID到任务的映射
    // const taskMap = new Map();
    // tasks.forEach(task => taskMap.set(task.id, task));

    // // 存储根任务（一级任务）
    // const rootTasks: any[] = [];
    // // 存储二级任务（按parent_task_id分组）
    // const childTasksMap = new Map();

    // // 第一次遍历：分离一级和二级任务
    // tasks.forEach(task => {
    //     if (task.parent_task_id === null) {
    //         // 一级任务
    //         rootTasks.push({
    //             id: task.id,
    //             name: task.task_data?.target || '',
    //             status: task.status,
    //             history: task.history || [],
    //             event_type: task.status === 'waiting_for_user_input' ? 'user_input' : '',
    //             call_reason: '',
    //             children: []  // 初始化子任务数组
    //         });
    //     } else {
    //         // 二级任务（按父ID分组）
    //         const parentId = task.parent_task_id;
    //         if (!childTasksMap.has(parentId)) {
    //             childTasksMap.set(parentId, []);
    //         }
    //         childTasksMap.get(parentId).push({
    //             id: task.id,
    //             name: task.task_data?.target || '',
    //             status: task.status,
    //             history: task.history || [],
    //             event_type: task.status === 'waiting_for_user_input' ? 'user_input' : '',
    //             call_reason: ''
    //             // 二级任务没有children字段
    //         });
    //     }
    // });

    // // 第二次遍历：将二级任务挂载到一级任务
    // rootTasks.forEach(rootTask => {
    //     const children = childTasksMap.get(rootTask.id) || [];
    //     rootTask.children = children;
    // });

    // return rootTasks;
}
