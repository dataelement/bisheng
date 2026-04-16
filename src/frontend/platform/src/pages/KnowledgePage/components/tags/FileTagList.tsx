import { Badge } from "@/components/bs-ui/badge";
import { Plus } from "lucide-react";
import { useTranslation } from "react-i18next";
import KnowledgeTagSelect from "./KnowledgeTagSelect";
import type { KnowledgeTagItem } from "@/controllers/API/knowledgeTags";

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
        <div className="flex flex-wrap items-center gap-1 min-h-[32px]">
            {tags.map(tag => (
                <Badge 
                    key={tag.id} 
                    variant="gray" 
                    className="max-w-[100px] truncate"
                    title={tag.name}
                >
                    {tag.name}
                </Badge>
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
                        className="flex items-center gap-0.5 px-1 py-0.5 text-xs text-primary hover:bg-primary/10 rounded transition-colors border border-dashed border-primary"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <Plus size={12} />
                        {t('addTag')}
                    </button>
                </KnowledgeTagSelect>
            )}
        </div>
    );
}
