// src/hooks/useLinsightManager.ts
import { useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useState } from 'react';
import {
    useRecoilCallback,
    useRecoilState,
    useRecoilValue,
    useSetRecoilState
} from 'recoil';
import { ConversationData, QueryKeys } from '~/data-provider/data-provider/src';
import { activeSessionIdState, LinsightInfo, linsightMapState, submissionState, SubmissionState } from '~/store/linsight';
import {
    addConversation
} from '~/utils';


export const useLinsightManager = () => {
    const [linsightMap, setLinsightMap] = useRecoilState(linsightMapState);
    const setActiveSessionId = useSetRecoilState(activeSessionIdState);

    // 创建新会话信息
    const createLinsight = useCallback((sessionId: string, initialData: Omit<LinsightInfo, 'id'>) => {
        const newLinsight: LinsightInfo = {
            id: sessionId,
            ...initialData
        };

        setLinsightMap(prevMap => {
            const newMap = new Map(prevMap);
            newMap.set(sessionId, newLinsight);
            return newMap;
        });

        setActiveSessionId(sessionId);
        return sessionId;
    }, [setLinsightMap, setActiveSessionId]);

    // 更新会话信息
    const updateLinsight = useCallback((sessionId: string, update: Partial<LinsightInfo>) => {
        setLinsightMap(prevMap => {
            if (!prevMap.has(sessionId)) return prevMap;

            const newMap = new Map(prevMap);
            const current = newMap.get(sessionId)!;
            newMap.set(sessionId, {
                ...current,
                ...update
            });
            return newMap;
        });
    }, [setLinsightMap]);

    // 获取会话信息
    const getLinsight = useCallback((sessionId: string) => {
        return linsightMap.get(sessionId) || null;
    }, [linsightMap]);

    // 切换当前会话
    const switchSession = useCallback((sessionId: string) => {
        setActiveSessionId(sessionId);
    }, [setActiveSessionId]);

    return {
        createLinsight,
        updateLinsight,
        getLinsight,
        switchSession,
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


export const useLinsightSessionManager = (sessionId) => {
    const linsightSubmission = useRecoilValue(submissionState(sessionId));
    // 添加或更新会话状态
    const setLinsightSubmission = useRecoilCallback(({ set }) =>
        (sessionId: string, state: SubmissionState) => {
            set(submissionState(sessionId), state);
        },
        []
    );

    // 清空指定会话状态
    const clearLinsightSubmission = useRecoilCallback(({ set }) =>
        (sessionId: string) => {
            set(submissionState(sessionId), null);
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
 * @param sessionId 
 * sessionId规则说明
 * 新建会话 [new]
 * 重新执行 [会话id-版本id]
 */
export const useGenerateSop = (sessionId) => {
    const [loading, setLoading] = useState(false);
    const { linsightSubmission, clearLinsightSubmission } = useLinsightSessionManager(sessionId)
    const { createLinsight } = useLinsightManager()
    const queryClient = useQueryClient();

    useEffect(() => {
        if (linsightSubmission) {
            console.log('linsightSubmission :>> ', linsightSubmission);
            setLoading(true)

            if (linsightSubmission.isNew) {
                // SSE()
                // 生成sop, 返回versionId, title, chatId
                createLinsight(sessionId, {
                    status: '',
                    tools: linsightSubmission.tools, // TODO 过滤掉关闭的;合并用户上传的文件?
                    files: linsightSubmission.files,
                    user_id: 0,
                    question: linsightSubmission.question,
                    knowledge_enabled: false,
                    sop: '### markdown内容的内容',
                    sop_map: {},
                    execute_feedback: null,
                    version: '',
                    create_time: '',
                    session_id: '',
                    output_result: undefined,
                    score: null,
                    has_reexecute: false,
                    update_time: '',
                    title: "New Chat",
                    tasks: []
                })
                // submit => 加载SOP => 创建新会话
                // 新建会话
                queryClient.setQueryData<ConversationData>([QueryKeys.allConversations], (convoData) => {
                    if (!convoData) {
                        return convoData;
                    }
                    return addConversation(convoData, {
                        conversationId: "e5627e5730464772ad3c1a011e880b68",
                        createdAt: "",
                        endpoint: null,
                        endpointType: null,
                        model: "deepseek-chat",
                        title: "New Chat",
                        tools: [],
                        updatedAt: ""
                    });
                });
            }

            clearLinsightSubmission(sessionId)
        }
    }, [linsightSubmission])
}