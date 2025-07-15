// src/hooks/useLinsightManager.ts
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
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
import { activeSessionIdState, LinsightInfo, linsightMapState, submissionState, SubmissionState } from '~/store/linsight';
import {
    addConversation,
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
    const getLinsight = useCallback((versionId: string) => {
        return linsightMap.get(versionId) || null;
    }, [linsightMap]);

    // 切换当前会话
    const switchSession = useCallback((versionId: string) => {
        setActiveSessionId(versionId);
    }, [setActiveSessionId]);

    // 切换会话，更新会话信息
    const switchAndUpdateLinsight = useCallback((versionId: string, update: any) => {
        const linsight = getLinsight(versionId)
        console.log('update :>> ', update);
        if (linsight) return;

        const { status, execute_feedback, output_result, tasks, files, ...params } = update
        let newStatus = ''
        switch (status) {
            case 'not_started':
                newStatus = SopStatus.SopGenerated;
                break;
            case 'in_progress':
                newStatus = SopStatus.Running;
                break;
            case 'completed':
                newStatus = execute_feedback ? SopStatus.FeedbackCompleted : SopStatus.completed;
                break;
            case 'terminated':
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
            summary: output_result?.answer,
            status: newStatus,
            files: files?.map(file => ({ ...file, file_name: decodeURIComponent(file.original_filename) })) || [],
            tasks: buildTaskTree(tasks),
            file_list: output_result?.final_files || []
        }

        createLinsight(versionId, data);
    }, [])

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

    const mockGenerateSop = (versionId: string, feedback?: string) => {
        console.log('Mock SSE started for version:', versionId, linsightSubmission);
        setLoading(false)
        updateLinsight(versionId, {
            status: SopStatus.SopGenerating,
        })

        setTimeout(() => {
            updateLinsight(versionId, {
                sop: mockContent
            })
        }, 2000)

        setTimeout(() => {
            updateLinsight(versionId, {
                status: SopStatus.SopGenerated,
            })
        }, 3000)
    };

    // 生成会话
    const generateSop = (_versionId, feedback?: string) => {
        // return mockGenerateSop(_versionId, feedback)  // mock
        const payload = {
            linsight_session_version_id: _versionId,
            feedback_content: feedback,
            reexecute: false
        }
        if (feedback) {
            payload.previous_session_version_id = versionId
            payload.reexecute = true
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
                sop: content.replace('```markdown\n', '')
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
        })

        sse.addEventListener('open', () => {
            console.log('connection is opened');
            setLoading(false)
            updateLinsight(_versionId, {
                status: SopStatus.SopGenerating,
            })
        });

        sse.addEventListener('error', async (e: MessageEvent) => {
            console.error('object :>> ', e);
            showToast({
                message: 'SOP 生成失败，请联系管理员检查灵思任务执行模型状态',
                status: 'error',
            });
            setLoading(false)
            updateLinsight(_versionId, {
                status: SopStatus.SopGenerating,
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
                        name: linsight_session_version.version.replace('T', ' ')
                    }, ...prevVersions])

                    // replaceUrl
                    window.history.replaceState({}, '', `${__APP_ENV__.BASE_URL}/sop/${linsight_session_version.session_id}`);

                    createLinsight(versionId, {
                        status: SopStatus.SopGenerating, //linsight_session_version.status,
                        tools: tools,
                        files: linsight_session_version.files?.map(file => ({ ...file, file_name: decodeURIComponent(file.original_filename) })) || [],
                        user_id: linsight_session_version.user_id,
                        question: linsightSubmission.question,
                        org_knowledge_enabled: false,
                        personal_knowledge_enabled: false,
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
                        file_list: []
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
                    generateSop(versionId)
                })

                sse.addEventListener('open', () => {
                    console.log('connection is opened');
                });

                sse.addEventListener('error', async (e: MessageEvent) => {
                    console.error('object :>> ', e);
                    showToast({
                        message: 'SOP 生成失败，请联系管理员检查灵思任务执行模型状态',
                        status: 'error',
                    });
                    setLoading(false)
                    updateLinsight(versionId, {
                        status: SopStatus.SopGenerating,
                    })
                })
                sse.stream();
            } else {
                generateSop(versionId, linsightSubmission.feedback)
            }

            clearLinsightSubmission(versionId)
        }
    }, [linsightSubmission])

    return loading
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
                        tool_key: api.tool_key
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
    // 创建任务ID到任务的映射
    const taskMap = new Map();
    tasks.forEach(task => taskMap.set(task.id, task));

    // 存储根任务（一级任务）
    const rootTasks: any[] = [];
    // 存储二级任务（按parent_task_id分组）
    const childTasksMap = new Map();

    // 第一次遍历：分离一级和二级任务
    tasks.forEach(task => {
        if (task.parent_task_id === null) {
            // 一级任务
            rootTasks.push({
                id: task.id,
                name: task.task_data?.target || '',
                status: task.status,
                history: task.history || [],
                event_type: task.status === 'waiting_for_user_input' ? 'user_input' : '',
                call_reason: '',
                children: []  // 初始化子任务数组
            });
        } else {
            // 二级任务（按父ID分组）
            const parentId = task.parent_task_id;
            if (!childTasksMap.has(parentId)) {
                childTasksMap.set(parentId, []);
            }
            childTasksMap.get(parentId).push({
                id: task.id,
                name: task.task_data?.target || '',
                status: task.status,
                history: task.history || [],
                event_type: task.status === 'waiting_for_user_input' ? 'user_input' : '',
                call_reason: ''
                // 二级任务没有children字段
            });
        }
    });

    // 第二次遍历：将二级任务挂载到一级任务
    rootTasks.forEach(rootTask => {
        const children = childTasksMap.get(rootTask.id) || [];
        rootTask.children = children;
    });

    return rootTasks;
}

const mockContent = `
# SOP: 中美贸易逆顺差分析

## 问题概述

本SOP旨在帮助用户理解中美两国之间存在的贸易逆差或顺差情况，包括但不限于主要商品类别、影响因素及历史趋势等方面。适用于对国际贸易感兴趣的研究者、政策制定者以及相关行业从业者。

## 所需工具和资源

- **Bing搜索引擎** - 获取关于中美贸易数据的文章、研究报告等资料。
- **世界银行公开数据库** - 提供详细的国家间贸易统计数据。
- **中国海关总署网站** - 官方发布最新的进出口统计信息。
- **美国商务部网站** - 同样提供官方发布的贸易数据。

### 工具使用最佳实践

- 使用Bing搜索时，请确保输入具体的关键词以获得更准确的结果，例如“中美贸易逆差”、“中美贸易数据分析”等。
- 访问世界银行数据库时，利用其内置的筛选功能快速定位到中美之间的贸易数据。
- 在查阅中国海关总署与美国商务部提供的信息时，注意查看最新发布的报告，并关注官方解释部分，以便更好地理解背景。

## 详细的步骤说明

1. **确定研究重点**

   - 明确想要深入探讨的具体方面，如特定年份内的变化趋势、主要受影响的商品种类等。
2. **收集基础数据**

   - 利用 bing_search函数查找关于中美贸易概况的基础介绍性文章。
   - 通过访问@world_bank_database获取两国间历年来的详细贸易数额记录。
3. **分析关键指标**

   - 结合从中国海关总署(@china_customs)和美国商务部(@us_department_of_commerce)获取的数据，对比分析不同时间段内双方出口与进口额的变化。
4. **识别影响因素**

   - 再次运用 bing_search，专注于寻找专家对于造成当前贸易状况背后原因的分析。
5. **整理并总结发现**

   - 将所有收集到的信息整合起来，提炼出导致中美贸易不平衡的主要原因及其潜在影响。
6. **撰写最终报告**

   - 如果需要生成一份详尽文档，则应先规划好大纲结构，然后按照@write_document的方式逐步完成每个章节的内容编写工作。

## 可能遇到的问题及解决方案

- **问题：数据解读困难**

  - **解决方案**：尝试联系该领域的专家进行咨询；同时也可以参考更多可视化图表来辅助理解复杂的数据集。
- **问题：难以找到足够全面的历史数据**

  - **解决方案**：除了官方渠道外，还可以探索学术期刊中发表的相关研究论文，这些往往包含了长期追踪调查所得出的结论。
- **问题：面对大量信息感到无从下手**

  - **解决方案**：建议采用分步走策略，即先从最基础的概念开始学习，再逐渐过渡到更深层次的分析；此外，建立一个清晰的目标列表也有助于保持研究方向的一致性。
`