import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, MessageSquare, ThumbsUp, Eye } from "lucide-react";
import { Button } from "~/components/ui/Button";
import { Badge } from "~/components/ui/Badge";
import { Avatar, AvatarName } from "~/components/ui/Avatar";
import { Card, CardContent, CardHeader } from "~/components/ui/Card";
import { Separator } from "~/components/ui/Separator";
import { Skeleton } from "~/components/ui/Skeleton";
import useLocalize from "~/hooks/useLocalize";
import { getQuestionDetailApi, getQuestionAnswersApi, type QuestionDetail, type AnswerDetail } from "~/api/qaExpert";
import { cn } from "~/utils";

const STATUS_MAP: Record<string | number, string> = {
    unsolved: "com_qa_expert_status_unsolved",
    solved: "com_qa_expert_status_solved",
    closed: "com_qa_expert_status_closed",
    pending: "com_qa_expert_status_pending",
    0: "com_qa_expert_status_unsolved",
    1: "com_qa_expert_status_solved",
    2: "com_qa_expert_status_closed",
    3: "com_qa_expert_status_pending",
};

function resolveStatusKey(status?: string | number | null): string {
    if (status === undefined || status === null) return "com_qa_expert_status_unsolved";
    return STATUS_MAP[status] ?? "com_qa_expert_status_unsolved";
}

function formatDateTime(value?: string): string {
    if (!value) return "";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString("zh-CN", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
    });
}

function AnswerCard({
    answer,
    isAccepted,
    localize,
}: {
    answer: AnswerDetail;
    isAccepted: boolean;
    localize: ReturnType<typeof useLocalize>;
}) {
    const expertName = answer.expert_name ?? answer.expert_info?.expert_name ?? "";

    return (
        <Card className={cn("gap-4", isAccepted && "border-green-500/50 bg-green-50/30")}>
            <CardHeader className="px-5 pb-0 pt-5">
                <div className="flex items-center justify-between gap-3">
                    <div className="flex items-center gap-2">
                        <Avatar className="size-8">
                            <AvatarName name={expertName} className="text-xs" />
                        </Avatar>
                        <div className="flex flex-col">
                            <span className="text-sm font-medium text-[#1d2129]">
                                {expertName || localize("com_qa_expert_expert_answer")}
                            </span>
                            <span className="text-xs text-[#86909c]">{formatDateTime(answer.created_at)}</span>
                        </div>
                    </div>
                    {isAccepted && (
                        <Badge
                            variant="default"
                            className="gap-1 bg-green-100 text-green-700 hover:bg-green-100"
                        >
                            <CheckCircle2 className="size-3.5" />
                            {localize("com_qa_expert_accepted_answer")}
                        </Badge>
                    )}
                </div>
            </CardHeader>
            <CardContent className="px-5 pb-5">
                <div className="whitespace-pre-wrap text-[15px] leading-7 text-[#1d2129]">
                    {answer.content}
                </div>
                <div className="mt-4 flex items-center gap-5 text-sm text-[#86909c]">
                    <span className="inline-flex items-center gap-1">
                        <ThumbsUp className="size-4" />
                        {localize("com_qa_expert_vote_count", { count: String(answer.vote_count ?? 0) })}
                    </span>
                    <span className="inline-flex items-center gap-1">
                        <MessageSquare className="size-4" />
                        {localize("com_qa_expert_comment_count", { count: String(answer.comment_count ?? 0) })}
                    </span>
                </div>
            </CardContent>
        </Card>
    );
}

export default function QuestionDetailPage() {
    const localize = useLocalize();
    const { questionId } = useParams<{ questionId: string }>();
    const numericId = questionId ? Number(questionId) : NaN;
    const isValidId = Number.isFinite(numericId) && numericId > 0;

    const {
        data: question,
        isLoading: isQuestionLoading,
        error: questionError,
        refetch: refetchQuestion,
    } = useQuery<QuestionDetail>({
        queryKey: ["qaExpertQuestionDetail", numericId],
        queryFn: () => getQuestionDetailApi(numericId),
        enabled: isValidId,
    });

    const {
        data: answersData,
        isLoading: isAnswersLoading,
        error: answersError,
        refetch: refetchAnswers,
    } = useQuery<QuestionAnswers>({
        queryKey: ["qaExpertQuestionAnswers", numericId],
        queryFn: () => getQuestionAnswersApi(numericId),
        enabled: isValidId,
    });

    const answers = answersData?.answers ?? [];
    const isLoading = isQuestionLoading || isAnswersLoading;
    const error = questionError || answersError;

    const statusKey = useMemo(() => resolveStatusKey(question?.status), [question?.status]);

    if (!isValidId) {
        return (
            <div className="flex h-full items-center justify-center text-[#86909c]">
                {localize("com_qa_expert_invalid_question_id")}
            </div>
        );
    }

    return (
        <div className="mx-auto h-full max-w-4xl overflow-y-auto px-6 py-8">
            <Button
                variant="ghost"
                className="mb-4 -ml-3 h-8 px-3 text-[#4e5969] hover:text-[#1d2129]"
                onClick={() => window.history.back()}
            >
                <ArrowLeft className="mr-1 size-4" />
                {localize("com_qa_expert_back")}
            </Button>

            {isLoading ? (
                <div className="space-y-4">
                    <Skeleton className="h-8 w-3/4" />
                    <Skeleton className="h-5 w-1/3" />
                    <Skeleton className="h-32 w-full" />
                    <Skeleton className="h-24 w-full" />
                </div>
            ) : error ? (
                <div className="flex flex-col items-center justify-center gap-3 py-20 text-[#86909c]">
                    <p>{localize("com_qa_expert_load_failed")}</p>
                    <Button variant="outline" onClick={() => { void refetchQuestion(); void refetchAnswers(); }}>
                        {localize("com_qa_expert_retry")}
                    </Button>
                </div>
            ) : question ? (
                <div className="space-y-6">
                    <div>
                        <div className="flex flex-wrap items-start gap-3">
                            <h1 className="flex-1 text-xl font-semibold leading-8 text-[#1d2129]">
                                {question.title}
                            </h1>
                            <Badge variant="outline" className="shrink-0 text-[#165dff]">
                                {localize(statusKey)}
                            </Badge>
                        </div>
                        <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-[#86909c]">
                            <span>{localize("com_qa_expert_business_domain")}：{question.business_domain}</span>
                            <span className="inline-flex items-center gap-1">
                                <Eye className="size-4" />
                                {localize("com_qa_expert_view_count", { count: String(question.view_count ?? 0) })}
                            </span>
                            <span className="inline-flex items-center gap-1">
                                <ThumbsUp className="size-4" />
                                {localize("com_qa_expert_vote_count", { count: String(question.vote_count ?? 0) })}
                            </span>
                            <span>{formatDateTime(question.created_at)}</span>
                        </div>
                    </div>

                    <Card>
                        <CardContent className="px-5 py-5">
                            <div className="whitespace-pre-wrap text-[15px] leading-7 text-[#1d2129]">
                                {question.description}
                            </div>
                        </CardContent>
                    </Card>

                    <Separator />

                    <div>
                        <h2 className="mb-4 text-base font-semibold text-[#1d2129]">
                            {localize("com_qa_expert_answers_title")}
                            <span className="ml-2 text-sm font-normal text-[#86909c]">
                                {localize("com_qa_expert_answer_count", { count: String(answers.length) })}
                            </span>
                        </h2>

                        {answers.length === 0 ? (
                            <div className="rounded-lg border border-dashed border-[#e5e6eb] py-12 text-center text-sm text-[#86909c]">
                                {localize("com_qa_expert_no_answers")}
                            </div>
                        ) : (
                            <div className="space-y-4">
                                {answers.map((answer) => (
                                    <AnswerCard
                                        key={answer.id}
                                        answer={answer}
                                        isAccepted={answer.id === question.adopted_answer_id}
                                        localize={localize}
                                    />
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            ) : null}
        </div>
    );
}
