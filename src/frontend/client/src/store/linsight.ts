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
    /**
     * Structured failure classification from the backend error_message event
     * (灵思LLM容错). Drives the friendly, localized error card: `error_type`
     * selects the copy (content_filter / quota_exhausted / network_timeout …),
     * `detail` is the raw provider text shown under "view details". Absent for
     * legacy/unclassified failures — the card falls back to a generic message.
     */
    taskErrorInfo?: {
        error_code?: number;
        error_type?: string;
        detail?: string;
    };
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
    /**
     * F035 multi-turn: snapshots of completed prior rounds in this conversation.
     * The top-level fields (question / tasks / sessionSteps / output_result)
     * always represent the CURRENTLY-ACTIVE round (WS events update them in
     * place). On a follow-up turn we snapshot the active round into `history`
     * then reset the active fields, so ExecutionFlow can render every round
     * stacked. The agent keeps full context server-side (same thread_id), so
     * each round still reads against the whole conversation.
     */
    history?: LinsightRoundSnapshot[];
}

export type LinsightRoundSnapshot = {
    /**
     * Stable per-round identity for React keys. All rounds share one
     * session_version (versionId), so a round needs its own id to key reliably
     * across re-renders (array index keys break when rounds re-order/append).
     * Assigned when the round is snapshotted into history.
     */
    roundId: string;
    question: string;
    tasks: any[];
    sessionSteps: any[];
    output_result: null | any;
    file_list: any[];
    /**
     * Terminal state carried into the snapshot so a finished round can render
     * its own stopped/error banner in history (not just the active round).
     */
    status?: string;
    taskError?: string;
    taskErrorInfo?: {
        error_code?: number;
        error_type?: string;
        detail?: string;
    };
};

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
    /** F035: existing session id to continue (follow-up round); undefined = new session. */
    sessionId?: string;
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

