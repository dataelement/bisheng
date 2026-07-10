import request from "./request";

interface ApiResponse<T> {
    status_code: number;
    status_message: string;
    data: T;
}

export interface ExpertInfo {
    id: number;
    user_id: number;
    expert_name: string;
    introduction?: string;
    level?: string;
    verified?: boolean;
}

export interface QuestionDetail {
    id: number;
    title: string;
    description: string;
    business_domain: string;
    status: string | number;
    user_id: number;
    anonymous?: boolean;
    attachments?: string[];
    related_docs?: number[];
    invited_experts?: number[];
    experts_names?: string;
    adopted_answer_id?: number | null;
    vote_count: number;
    answer_count: number;
    view_count: number;
    created_at: string;
    updated_at: string;
    answers?: AnswerDetail[];
    expert_status?: Record<string, unknown>;
}

export interface AnswerDetail {
    id: number;
    question_id: number;
    user_id: number;
    expert_id?: number | null;
    expert_name?: string | null;
    content: string;
    status: string | number;
    attachments?: string[];
    related_docs?: number[];
    vote_count: number;
    comment_count: number;
    created_at: string;
    updated_at: string;
    expert_info?: ExpertInfo | null;
    comments?: CommentDetail[];
}

export interface CommentDetail {
    id: number;
    answer_id: number;
    question_id: number;
    user_id: number;
    user_name?: string;
    content: string;
    is_follow_up: boolean;
    vote_count: number;
    created_at: string;
}

export interface QuestionAnswers {
    answers: AnswerDetail[];
    total: number;
}

function extractData<T>(response: unknown): T {
    const wrapper = (response ?? {}) as Record<string, unknown>;
    return (wrapper.data ?? wrapper) as T;
}

export async function getQuestionDetailApi(questionId: number | string): Promise<QuestionDetail> {
    const res = await request.get<ApiResponse<QuestionDetail>>(
        `/api/v1/qa_experts/questions/${questionId}`
    );
    return extractData(res);
}

export async function getQuestionAnswersApi(questionId: number | string): Promise<QuestionAnswers> {
    const res = await request.get<ApiResponse<QuestionAnswers | AnswerDetail[]>>(
        `/api/v1/qa_experts/answers/${questionId}`
    );
    const payload = extractData<QuestionAnswers | AnswerDetail[]>(res);
    if (Array.isArray(payload)) {
        return { answers: payload, total: payload.length };
    }
    const data = payload as QuestionAnswers;
    return {
        answers: data?.answers ?? [],
        total: data?.total ?? 0,
    };
}
