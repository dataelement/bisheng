import { ChevronDown, ChevronUp, MessageCircle } from "lucide-react";
import { useState } from "react";
import { Avatar, AvatarName } from "~/components/ui/Avatar";
import { Button } from "~/components/ui/Button";
import { Skeleton } from "~/components/ui/Skeleton";
import useLocalize from "~/hooks/useLocalize";
import { useCommentsQuery } from "../hooks/useQuestionDetail";
import type { CommentDetail } from "~/api/qaExpert";

interface CommentListProps {
    answerId: number;
    questionId?: number;
    totalCount: number;
}

function CommentItem({ comment }: { comment: CommentDetail }) {
    const localize = useLocalize();
    const displayName = comment.user_name || `User ${comment.user_id}`;
    return (
        <div className="flex gap-3 py-3">
            <Avatar className="size-8">
                <AvatarName name={displayName} className="text-xs" />
            </Avatar>
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex items-center gap-2 text-[13px]">
                    <span className="font-medium text-[#1d2129]">{displayName}</span>
                    {comment.is_follow_up && (
                        <span className="text-[#86909c]">({localize("com_qa_expert_detail_follow_up")})</span>
                    )}
                </div>
                <div className="whitespace-pre-wrap text-[14px] leading-relaxed text-[#4e5969]">
                    {comment.content}
                </div>
            </div>
        </div>
    );
}

export function CommentList({ answerId, questionId, totalCount }: CommentListProps) {
    const localize = useLocalize();
    const [open, setOpen] = useState(false);
    const { data, isLoading } = useCommentsQuery(answerId, questionId);

    if (totalCount <= 0) return null;

    return (
        <div className="mt-3 border-t border-[#f2f3f5] pt-2">
            <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setOpen((v) => !v)}
                className="h-7 gap-1 px-2 text-[13px] text-[#4e5969] hover:bg-[#f7f8fa] hover:text-[#165dff]"
            >
                <MessageCircle className="size-4" />
                {localize("com_qa_expert_detail_comments_count", { count: totalCount })}
                {open ? <ChevronUp className="size-3.5" /> : <ChevronDown className="size-3.5" />}
            </Button>

            {open && (
                <div className="pl-1">
                    {isLoading ? (
                        <div className="space-y-2 py-2">
                            <Skeleton className="h-4 w-3/4" />
                            <Skeleton className="h-4 w-1/2" />
                        </div>
                    ) : data?.comments.length ? (
                        <div className="divide-y divide-[#f2f3f5]">
                            {data.comments.map((comment) => (
                                <CommentItem key={comment.id} comment={comment} />
                            ))}
                        </div>
                    ) : (
                        <div className="py-3 text-[13px] text-[#86909c]">
                            {localize("com_qa_expert_detail_no_comments")}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
