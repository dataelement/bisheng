// src/state/linsightState.ts
import { atom, atomFamily, selectorFamily, useRecoilState } from 'recoil';

export type LinsightInfo = {
    title: string;
    user_id: number;
    question: string;
    knowledge_enabled: boolean;
    sop: null | string;
    sop_map: { [key in string]: string };
    status: string;
    execute_feedback: null | string;
    version: string;
    create_time: string;
    session_id: string;
    tools: {
        tool_id: string;
    }[];
    files: {
        file_id: string;
    }[];
    output_result: null | any;
    score: null | number;
    has_reexecute: boolean;
    id: string;
    update_time: string;
    tasks: {
        session_version_id: string;
        parent_task_id: string | null;
        previous_task_id: string | null;
        next_task_id: string | null;
        task_type: string;
        task_data: any | null;
        input_prompt: string | null;
        user_input: string | null;
        history: {
            step: string;
        }[] | null;
        status: string;
        result: any | null;
    }[]
}

// 使用 Map 结构存储 {会话id-版本id: linsight信息}
export const linsightMapState = atom<Map<string, LinsightInfo>>({
    key: 'linsightMapState',
    default: new Map(),
});

// 当前活动会话ID
export const activeSessionIdState = atom<string | null>({
    key: 'activeSessionIdState',
    default: null,
});




export type ToolConfig = {
    id: string;
    name: string;
    params?: Record<string, any>;
};

export type SubmissionState = {
    isNew: boolean;
    files: string[];
    question: string;
    tools: ToolConfig[];
    model: string;
    enableWebSearch: boolean;
    useKnowledgeBase: boolean;
};

// 使用atomFamily管理每个会话的状态 会话id-版本id:状态
export const submissionState = atomFamily<SubmissionState | null, string>({
    key: 'submissionState',
    default: null, // 初始状态为null
});