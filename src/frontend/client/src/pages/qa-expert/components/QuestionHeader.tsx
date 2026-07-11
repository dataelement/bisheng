import { Eye, MessageSquare, ThumbsUp } from "lucide-react";
import { Badge } from "~/components/ui/Badge";
import type { QuestionDetail } from "~/api/qaExpert";
import useLocalize from "~/hooks/useLocalize";
import { cn } from "~/utils";

interface QuestionHeaderProps {
    question: QuestionDetail;
}

function QuestionStatusBadge({ status }: { status?: string }) {
    const localize = useLocalize();
    const config: Record<string, { key: string; className: string }> = {
        solved: {
            key: "com_qa_expert_detail_status_solved",
            className: "bg-green-100 text-green-700",
        },
        closed: {
            key: "com_qa_expert_detail_status_closed",
            className: "bg-gray-100 text-gray-600",
        },
        unsolved: {
            key: "com_qa_expert_detail_status_unsolved",
            className: "bg-orange-100 text-orange-700",
        },
    };
    const item = config[status || "unsolved"] ?? config.unsolved;
    return (
        <Badge className={cn("text-xs font-normal", item.className)}>
            {localize(item.key as any)}
        </Badge>
    );
}

export function QuestionHeader({ question }: QuestionHeaderProps) {
    const localize = useLocalize();
    const createdAt = question.created_at
        ? new Date(question.created_at).toLocaleString()
        : "";

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap items-center gap-2">
                <QuestionStatusBadge status={question.status} />
                {question.business_domain && (
                    <Badge variant="gray">{question.business_domain}</Badge>
                )}
            </div>

            <h1 className="text-[20px] font-semibold leading-tight text-[#1d2129]">
                {question.title}
            </h1>

            <div className="flex flex-wrap items-center gap-4 text-[13px] text-[#86909c]">
                <span className="inline-flex items-center gap-1">
                    <Eye className="size-4" />
                    {question.view_count ?? 0}
                </span>
                <span className="inline-flex items-center gap-1">
                    <MessageSquare className="size-4" />
                    {question.answer_count ?? 0}
                </span>
                <span className="inline-flex items-center gap-1">
                    <ThumbsUp className="size-4" />
                    {question.vote_count ?? 0}
                </span>
                {createdAt && <span>{createdAt}</span>}
            </div>

            <div className="whitespace-pre-wrap text-[15px] leading-relaxed text-[#1d2129]">
                {question.description}
            </div>

            {question.attachments && question.attachments.length > 0 && (
                <div className="space-y-2">
                    <div className="text-[13px] font-medium text-[#4e5969]">
                        {localize("com_qa_expert_detail_attachments")}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {question.attachments.map((url, idx) => (
                            <a
                                key={idx}
                                href={url}
                                target="_blank"
                                rel="noreferrer"
                                className="max-w-[240px] truncate rounded-md bg-[#f2f3f5] px-3 py-1.5 text-[13px] text-[#165dff] hover:underline"
                            >
                                {url.split("/").pop() || url}
                            </a>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}
