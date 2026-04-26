import { Badge } from "@/components/bs-ui/badge";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/bs-ui/tooltip";
import { truncateString } from "@/util/utils";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import KnowledgeTagSelect from "./KnowledgeTagSelect";
import type { KnowledgeTagItem } from "@/controllers/API/knowledgeTags";

const FILE_TAG_DISPLAY_MAX_LENGTH = 12;

interface FileTagListProps {
    knowledgeId: string | number;
    fileId: number;
    tags?: KnowledgeTagItem[];
    isEditable?: boolean;
    onUpdate: () => void;
}

export default function FileTagList({
    knowledgeId,
    fileId,
    tags = [],
    isEditable = true,
    onUpdate
}: FileTagListProps) {
    const { t } = useTranslation('knowledge');

    return (
        <TooltipProvider delayDuration={200}>
            <div className="flex flex-wrap items-center gap-1 min-h-[32px]">
                {tags.map(tag => {
                    const displayName = truncateString(tag.name, FILE_TAG_DISPLAY_MAX_LENGTH);
                    const isTruncated = displayName !== tag.name;

                    if (!isTruncated) {
                        return (
                            <Badge
                                key={tag.id}
                                variant="gray"
                                className="max-w-[100px] cursor-default truncate"
                                title={tag.name}
                            >
                                {displayName}
                            </Badge>
                        );
                    }

                    return (
                        <Tooltip key={tag.id}>
                            <TooltipTrigger asChild>
                                <Badge
                                    variant="gray"
                                    className="max-w-[100px] cursor-default truncate"
                                    title={tag.name}
                                >
                                    {displayName}
                                </Badge>
                            </TooltipTrigger>
                            <TooltipContent className="max-w-[320px] break-all whitespace-normal">
                                {tag.name}
                            </TooltipContent>
                        </Tooltip>
                    );
                })}

                {isEditable && (
                    <KnowledgeTagSelect
                        knowledgeId={knowledgeId}
                        fileIds={[fileId]}
                        initialTags={tags}
                        onUpdate={onUpdate}
                        isEditable={isEditable}
                    >
                        <button
                            className="flex items-center gap-0.5 px-1 py-0.5 text-xs text-primary hover:bg-primary/10 rounded transition-colors border border-dashed border-primary"
                            onClick={(e) => e.stopPropagation()}
                        >
                            <Plus size={12} />
                            {t('addTag')}
                        </button>
                    </KnowledgeTagSelect>
                )}
            </div>
        </TooltipProvider>
    );
}
