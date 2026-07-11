import { CheckCircle2, ThumbsUp } from "lucide-react";
import { Avatar, AvatarName } from "~/components/ui/Avatar";
import { Card, CardContent } from "~/components/ui/Card";
import { Separator } from "~/components/ui/Separator";
import useLocalize from "~/hooks/useLocalize";
import type { AnswerDetail } from "~/api/qaExpert";
import { CommentList } from "./CommentList";
import { cn } from "~/utils";

interface AnswerCardProps {
    answer: AnswerDetail;
    isAdopted: boolean;
}

export function AnswerCard({ answer, isAdopted }: AnswerCardProps) {
    const localize = useLocalize();
    const expertName = answer.expert_info?.expert_name || `User ${answer.user_id}`;
    const createdAt = answer.created_at
        ? new Date(answer.created_at).toLocaleString()
        : "";

    return (
        <Card className={cn("gap-4", isAdopted && "border-green-300 bg-green-50/30")}>
            <CardContent className="space-y-3">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <Avatar className="size-9">
                            <AvatarName name={expertName} className="text-xs" />
                        </Avatar>
                        <div className="flex flex-col">
                            <span className="text-[14px] font-medium text-[#1d2129]">{expertName}</span>
                            {createdAt && (
                                <span className="text-[12px] text-[#86909c]">{createdAt}</span>
                            )}
                        </div>
                    </div>
                    {isAdopted && (
                        <div className="inline-flex items-center gap-1 rounded-full bg-green-100 px-2.5 py-1 text-[12px] font-medium text-green-700">
                            <CheckCircle2 className="size-3.5" />
                            {localize("com_qa_expert_detail_adopted_label")}
                        </div>
                    )}
                </div>

                <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-[#1d2129]">
                    {answer.content}
                </div>

                {answer.attachments && answer.attachments.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                        {answer.attachments.map((url, idx) => (
                            <a
                                key={idx}
                                href={url}
                                target="_blank"
                                rel="noreferrer"
                                className="max-w-[200px] truncate rounded-md bg-[#f2f3f5] px-3 py-1.5 text-[12px] text-[#165dff] hover:underline"
                            >
                                {url.split("/").pop() || url}
                            </a>
                        ))}
                    </div>
                )}

                <Separator />

                <div className="flex items-center gap-4 text-[13px] text-[#86909c]">
                    <span className="inline-flex items-center gap-1">
                        <ThumbsUp className="size-4" />
                        {answer.vote_count ?? 0}
                    </span>
                </div>

                <CommentList
                    answerId={answer.id}
                    questionId={answer.question_id}
                    totalCount={answer.comment_count ?? 0}
                />
            </CardContent>
        </Card>
    );
}
