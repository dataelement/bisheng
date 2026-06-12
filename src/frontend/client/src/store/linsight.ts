// src/state/linsightState.ts
import { atom, atomFamily } from 'recoil';
import { ExtendedFile } from '~/common';

/**
 * Linsight session lifecycle status.
 * F035 Track H (P5): migrated out of the removed legacy SOPEditor component;
 * the SOP-stage values (SopGenerating/SopGenerated) are kept for backward
 * compatibility with historical sessions restored from the backend.
 */
export const enum SopStatus {
    /* 未开始 */
    NotStarted = 'not_started',
    /* SOP生成中 */
    SopGenerating = 'sopGenerating',
    /* SOP生成完成 */
    SopGenerated = 'sopGenerated',
    /* 开始执行 */
    Running = 'running',
    /* 执行完成 */
    completed = 'completed',
    /* 反馈完成 */
    FeedbackCompleted = 'feedbackCompleted',
    /* stop */
    Stoped = 'stoped'
}

export type LinsightInfo = {
    title: string;
    user_id: number;
    question: string;
    org_knowledge_enabled: boolean;
    personal_knowledge_enabled: boolean;
    sop: null | string;
    sopError: string;
    /** 用户输入的sop */
    inputSop: boolean;
    // sop_map: { [key in string]: string };
    status: string;
    execute_feedback: null | string;
    version: string;
    create_time: string;
    session_id: string;
    tools: {
        id: string | number;
        name: string;
        is_preset: boolean;
        children: ApiTool[];
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
            user_input: any;
            step: string;
        }[] | null;
        status: string;
        result: any | null;
        children: any[]
    }[],
    taskError: string;
    summary: string;
    file_list: any[];
    queueCount: number;
    /**
     * F035 Track H (P3): flow-level events whose task_id matches no task —
     * the session pseudo task (task_id == session_version_id), e.g. planning
     * stage steps and pre-planning clarify (user_input) requests. Appended by
     * the WS hook; rendered by Linsight/Execution/ExecutionFlow. Optional so
     * the legacy Sop view keeps working untouched until P5 removes it.
     */
    sessionSteps?: any[];
}

interface ApiTool {
    id: string | number;
    name: string;
    tool_key: string;
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
    files: {
        file_id: string;
        file_name: string;
        parsing_status: string;
    }[];
    question: string;
    feedback?: string;
    tools: ToolConfig[];
    model: string;
    /** F035 Track H: skill names picked in the task-mode input (enabled skills only). */
    skills?: string[];
    enableWebSearch: boolean;
    useKnowledgeBase: boolean;
    prevVersionId?: string;
    sameSopId?: string | number;
};

// 使用atomFamily管理每个会话的状态 会话id-版本id:状态
export const submissionState = atomFamily<SubmissionState | null, string>({
    key: 'submissionState',
    default: null, // 初始状态为null
});

// 上传文件管理
export const filesByIndex = atomFamily<Map<string, ExtendedFile>, string | number>({
    key: 'linsightFilesByIndex',
    default: new Map(),
});

// ── F035 Track H: task-mode unified input ────────────────────────────────────

export type TaskModeKnowledgeItem = {
    id: string;
    name: string;
    /** 'space' = personal knowledge space, 'org' = organization knowledge base */
    type: 'space' | 'org';
};

export type TaskModeToolItem = {
    id: string | number;
    name: string;
    checked: boolean;
    /** Raw tool object from bsConfig.linsightConfig.tools (used by convertTools on submit). */
    data?: any;
};

export type TaskModeSkill = {
    name: string;
    display_name: string;
    description?: string;
};

export type TaskModeContext = {
    knowledge: TaskModeKnowledgeItem[];
    tools: TaskModeToolItem[];
    files: any[];
};

/**
 * Session-level memory (PRD §4.1.2): knowledge / tools / files selections are
 * keyed per conversation and survive leaving task mode (navigate back to /c),
 * so they are refilled when the user re-enters task mode.
 */
export const taskModeContextState = atomFamily<TaskModeContext, string>({
    key: 'taskModeContextState',
    default: { knowledge: [], tools: [], files: [] },
});

/**
 * Skill selections are intentionally separate from taskModeContextState:
 * exiting task mode clears skills while keeping the rest (PRD §4.1.2).
 */
export const taskModeSkillsState = atomFamily<TaskModeSkill[], string>({
    key: 'taskModeSkillsState',
    default: [],
});

