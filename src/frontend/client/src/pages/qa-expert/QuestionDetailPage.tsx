import { useParams } from "react-router-dom";
import { useEffect } from "react";
import { Skeleton } from "~/components/ui/Skeleton";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import useLocalize from "~/hooks/useLocalize";
import { useAnswersQuery, useQuestionDetailQuery } from "./hooks/useQuestionDetail";
import { QuestionHeader } from "./components/QuestionHeader";
import { AnswerCard } from "./components/AnswerCard";
import { Separator } from "~/components/ui/Separator";

function QuestionSkeleton() {
    return (
        <div className="space-y-6">
            <div className="space-y-3">
                <Skeleton className="h-5 w-20" />
                <Skeleton className="h-8 w-3/4" />
                <Skeleton className="h-4 w-40" />
            </div>
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-32 w-full" />
        </div>
    );
}

function EmptyAnswers() {
    const localize = useLocalize();
    return (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-[#e5e6eb] bg-[#f9f9f9] py-12 text-[14px] text-[#86909c]">
            {localize("com_qa_expert_detail_no_answers")}
        </div>
    );
}

export default function QuestionDetailPage() {
    const { questionId: questionIdParam } = useParams<{ questionId: string }>();
    const questionId = Number(questionIdParam);
    const localize = useLocalize();
    const { showToast } = useToastContext();

    const {
        data: question,
        isLoading: isQuestionLoading,
        error: questionError,
    } = useQuestionDetailQuery(questionId);

    const {
        data: answersData,
        isLoading: isAnswersLoading,
        error: answersError,
    } = useAnswersQuery(questionId);

    useEffect(() => {
        if (questionError || answersError) {
            showToast({
                message: localize("com_qa_expert_detail_load_failed"),
                severity: NotificationSeverity.ERROR,
            });
        }
    }, [questionError, answersError, localize, showToast]);

    if (!Number.isFinite(questionId) || questionId <= 0) {
        return (
            <div className="flex h-full items-center justify-center text-[14px] text-[#86909c]">
                {localize("com_qa_expert_detail_invalid_question")}
            </div>
        );
    }

    const isLoading = isQuestionLoading || isAnswersLoading;
    const answers = answersData?.answers ?? [];

    return (
        <div className="flex h-full flex-col overflow-hidden bg-white">
            <div className="flex-1 overflow-y-auto px-6 py-6">
                {isLoading && !question ? (
                    <QuestionSkeleton />
                ) : question ? (
                    <div className="mx-auto max-w-3xl space-y-6">
                        <QuestionHeader question={question} />

                        <Separator />

                        <div className="space-y-4">
                            <h2 className="text-[16px] font-semibold text-[#1d2129]">
                                {localize("com_qa_expert_detail_answers_count", {
                                    count: answers.length,
                                })}
                            </h2>
                            {answers.length === 0 ? (
                                <EmptyAnswers />
                            ) : (
                                answers.map((answer) => (
                                    <AnswerCard
                                        key={answer.id}
                                        answer={answer}
                                        isAdopted={answer.id === question.adopted_answer_id}
                                    />
                                ))
                            )}
                        </div>
                    </div>
                ) : null}
            </div>
        </div>
    );
}
