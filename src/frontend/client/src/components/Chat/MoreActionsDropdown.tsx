import { useState } from "react";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import MoreCircle from "bisheng-design-system/src/icons/outlined/MoreCircle";
import FileExport from "bisheng-design-system/src/icons/outlined/FileExport";
import AddToKnowledgeBase from "bisheng-design-system/src/icons/outlined/AddToKnowledgeBase";
import { SingleIconButton } from "bisheng-design-system/src/components/Button";
import { cn } from "~/utils";
import { AddToKnowledgeModal } from "~/pages/Subscription/Article/AddToKnowledgeModal";

export type ExportFileType = "word" | "pdf" | "txt" | "markdown";

interface MoreActionsDropdownProps {
    onExport?: (type: ExportFileType) => void;
    className?: string;
    /** Article / message ID for knowledge space import */
    articleId?: string | number;
}

const exportOptions: { type: ExportFileType; label: string }[] = [
    { type: "word", label: "Word" },
    { type: "pdf", label: "PDF" },
    { type: "txt", label: "TXT" },
    { type: "markdown", label: "Markdown" },
];

export default function MoreActionsDropdown({
    onExport,
    className,
    articleId,
}: MoreActionsDropdownProps) {
    const [knowledgeModalOpen, setKnowledgeModalOpen] = useState(false);

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <SingleIconButton
                        variant="ghost"
                        size="mini"
                        icon={<MoreCircle />}
                        aria-label="更多"
                        className={cn("text-gray-400 hover:text-gray-600", className)}
                    />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" sideOffset={6} className="rounded-xl">
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger className="gap-2 font-normal">
                            <FileExport className="size-4 shrink-0" />
                            <span>导出为文件</span>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent sideOffset={9} alignOffset={-4} className="rounded-xl">
                            {exportOptions.map((opt) => (
                                <DropdownMenuItem
                                    key={opt.type}
                                    onClick={() => onExport?.(opt.type)}
                                >
                                    {opt.label}
                                </DropdownMenuItem>
                            ))}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>
                    <DropdownMenuItem
                        className="gap-2"
                        onClick={() => setKnowledgeModalOpen(true)}
                    >
                        <AddToKnowledgeBase className="size-4 shrink-0" />
                        <span>导入知识空间</span>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <AddToKnowledgeModal
                open={knowledgeModalOpen}
                onOpenChange={setKnowledgeModalOpen}
                articleId={articleId}
            />
        </>
    );
}
