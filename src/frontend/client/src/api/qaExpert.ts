import request from "./request";

export interface ExpertInfo {
  id: number;
  user_id: number;
  expert_name: string;
  introduction?: string | null;
  level: string;
  business_domains: string[];
  verified: boolean;
  answer_count?: number;
  adoption_count?: number;
  helpful_count?: number;
}

export interface QuestionDetail {
  id: number;
  title: string;
  description: string;
  business_domain: string;
  status: string;
  user_id: number;
  anonymous: boolean;
  attachments: string[];
  related_docs: number[];
  invited_experts: number[];
  experts_names?: string | null;
  adopted_answer_id?: number | null;
  vote_count: number;
  answer_count: number;
  view_count: number;
  created_at: string;
  updated_at: string;
  answers?: AnswerDetail[];
  expert_status?: Record<string, any>;
}

export interface AnswerDetail {
  id: number;
  question_id: number;
  user_id: number;
  expert_id?: number | null;
  content: string;
  status: string;
  attachments: string[];
  related_docs: number[];
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
  user_name?: string | null;
  content: string;
  is_follow_up: boolean;
  vote_count: number;
  created_at: string;
}

function unwrap<T>(response: any): T {
  const root = response ?? {};
  const statusCode = root?.status_code ?? root?.data?.status_code;
  if (statusCode && statusCode !== 200) {
    throw new Error(root?.status_message || root?.message || "qa expert api failed");
  }
  return (root?.data ?? root) as T;
}

export async function getQuestionDetailApi(questionId: number): Promise<QuestionDetail> {
  const resp = await request.get(`/api/v1/qa_experts/questions/${questionId}`);
  return unwrap<QuestionDetail>(resp);
}

export async function getAnswersApi(questionId: number): Promise<{
  answers: AnswerDetail[];
  total: number;
}> {
  const resp = await request.get(`/api/v1/qa_experts/answers/${questionId}`);
  const payload = unwrap<{ answers?: AnswerDetail[]; total?: number }>(resp);
  return {
    answers: payload.answers ?? [],
    total: payload.total ?? 0,
  };
}

export async function getCommentsApi(params: {
  answer_id: number;
  question_id?: number;
  page?: number;
  page_size?: number;
}): Promise<{ comments: CommentDetail[]; total: number }> {
  const resp = await request.post(`/api/v1/qa_experts/allcomments`, {
    answer_id: params.answer_id,
    question_id: params.question_id,
    page: params.page ?? 1,
    page_size: params.page_size ?? 100,
  });
  const payload = unwrap<{ comments?: CommentDetail[]; total?: number }>(resp);
  return {
    comments: payload.comments ?? [],
    total: payload.total ?? 0,
  };
}
