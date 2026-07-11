import { useQuery } from "@tanstack/react-query";
import {
    getAnswersApi,
    getCommentsApi,
    getQuestionDetailApi,
    type AnswerDetail,
    type CommentDetail,
    type QuestionDetail,
} from "~/api/qaExpert";

export function useQuestionDetailQuery(questionId: number) {
    return useQuery<QuestionDetail>({
        queryKey: ["qaExpert", "question", questionId],
        queryFn: () => getQuestionDetailApi(questionId),
        enabled: questionId > 0,
        staleTime: 60_000,
    });
}

export function useAnswersQuery(questionId: number) {
    return useQuery<{ answers: AnswerDetail[]; total: number }>({
        queryKey: ["qaExpert", "answers", questionId],
        queryFn: () => getAnswersApi(questionId),
        enabled: questionId > 0,
        staleTime: 60_000,
    });
}

export function useCommentsQuery(answerId: number, questionId?: number) {
    return useQuery<{ comments: CommentDetail[]; total: number }>({
        queryKey: ["qaExpert", "comments", answerId, questionId],
        queryFn: () =>
            getCommentsApi({
                answer_id: answerId,
                question_id: questionId,
                page: 1,
                page_size: 100,
            }),
        enabled: answerId >= 0,
        staleTime: 60_000,
    });
}
