import { truncateString } from "@/util/utils";
import { PenLine } from "lucide-react";
import { useTranslation } from "react-i18next";
import KnowledgeTagSelect from "./KnowledgeTagSelect";
import type { KnowledgeTagItem } from "@/controllers/API/knowledgeTags";

const FILE_TAG_DISPLAY_MAX_LENGTH = 18;

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
        <div className="group/file-tags flex min-h-[20px] items-center gap-1">
            {tags.map(tag => (
                <span
                    key={tag.id}
                    className="inline-flex max-w-[100px] items-center justify-center rounded-[4px] bg-white px-2 text-[12px] leading-5 text-[#4e5969]"
                    title={tag.name}
                >
                    <span className="truncate">{truncateString(tag.name, FILE_TAG_DISPLAY_MAX_LENGTH)}</span>
                </span>
            ))}

            {isEditable && (
                <KnowledgeTagSelect
                    knowledgeId={knowledgeId}
                    fileIds={[fileId]}
                    initialTags={tags}
                    onUpdate={onUpdate}
                    isEditable={isEditable}
                >
                    <button
                        className="flex size-5 shrink-0 items-center justify-center rounded-[4px] text-[#4e5969] opacity-0 transition-[opacity,color,background-color] hover:text-[#335CFF] group-hover:opacity-100 group-hover/file-tags:text-[#335CFF] group-hover/file-tags:opacity-100"
                        onClick={(e) => e.stopPropagation()}
                        title={t('addTag')}
                    >
                        <PenLine size={16} />
                    </button>
                </KnowledgeTagSelect>
            )}
        </div>
    );
}
