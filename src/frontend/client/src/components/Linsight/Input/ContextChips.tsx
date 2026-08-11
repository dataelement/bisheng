/**
 * F035 Track H: chip row above the textarea (spec §1, fig.7). Shows the
 * current task context — selected skills, knowledge spaces / org KBs and
 * attached files — each removable via "x". Tools never produce chips.
 */
import { Loader2, Paperclip, Sparkles, X } from 'lucide-react';
import BookOpen from '~/components/ui/icon/BookOpen';
import BooksIcon from '~/components/ui/icon/Books';
import type { TaskModeKnowledgeItem, TaskModeSkill } from '~/store/linsight';

export interface ContextAttachmentFile {
    clientId: string;
    name: string;
    isUploading?: boolean;
    file_id?: string;
    filepath?: string;
    filename?: string;
    file_name?: string;
    parsing_status?: string;
}

interface ContextChipsProps {
    skills: TaskModeSkill[];
    knowledge: TaskModeKnowledgeItem[];
    /** Files in picker order; supersedes legacy `files` + `uploadingFiles` split. */
    attachmentFiles?: ContextAttachmentFile[];
    /** @deprecated use attachmentFiles */
    files?: any[];
    /** @deprecated use attachmentFiles */
    uploadingFiles?: { id: string; name: string }[];
    onRemoveSkill: (skill: TaskModeSkill) => void;
    onRemoveKnowledge: (item: TaskModeKnowledgeItem) => void;
    onRemoveFile: (file: any) => void;
}

const Chip = ({
    icon,
    label,
    onRemove,
}: {
    icon: React.ReactNode;
    label: string;
    onRemove?: () => void;
}) => (
    <div className="group flex h-6 min-w-0 max-w-[160px] shrink-0 items-center rounded-[4px] bg-white px-2 text-xs text-slate-700 transition-colors duration-200 hover:bg-slate-50">
        {icon}
        <span className="min-w-0 flex-1 truncate text-left" title={label}>
            {label}
        </span>
        {onRemove && (
            <button
                type="button"
                onClick={onRemove}
                className="ml-0.5 flex size-4 shrink-0 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-200"
                aria-label="Remove"
            >
                <X size={12} />
            </button>
        )}
    </div>
);

export function ContextChips({
    skills,
    knowledge,
    attachmentFiles,
    files = [],
    uploadingFiles = [],
    onRemoveSkill,
    onRemoveKnowledge,
    onRemoveFile,
}: ContextChipsProps) {
    const orderedFiles: ContextAttachmentFile[] = attachmentFiles ?? [
        ...uploadingFiles.map((file) => ({
            clientId: file.id,
            name: file.name,
            isUploading: true,
        })),
        ...files.map((file) => ({
            clientId: file.clientId || file.file_id || file.filepath || file.name,
            name: file.filename || file.file_name || file.name || '',
            isUploading: false,
            ...file,
        })),
    ];

    const isEmpty =
        skills.length === 0 && knowledge.length === 0 && orderedFiles.length === 0;
    if (isEmpty) return null;

    return (
        <div className="mb-2 max-h-[72px] overflow-y-auto">
            <div className="flex flex-wrap gap-1">
                {orderedFiles.map((file) => (
                    <Chip
                        key={`att-${file.clientId}`}
                        icon={
                            file.isUploading ? (
                                <Loader2 className="mr-1 size-4 shrink-0 animate-spin text-[#999]" />
                            ) : (
                                <Paperclip className="mr-1 size-4 shrink-0 text-[#999]" />
                            )
                        }
                        label={file.name}
                        onRemove={file.isUploading ? undefined : () => onRemoveFile(file)}
                    />
                ))}
                {skills.map((skill) => (
                    <Chip
                        key={`skill-${skill.name}`}
                        icon={<Sparkles className="mr-1 size-4 shrink-0 text-[#999]" />}
                        label={skill.display_name}
                        onRemove={() => onRemoveSkill(skill)}
                    />
                ))}
                {knowledge.map((item) => (
                    <Chip
                        key={`${item.type}-${item.id}`}
                        icon={
                            item.type === 'space' ? (
                                <BookOpen className="mr-1 size-4 shrink-0 text-[#999]" />
                            ) : (
                                <BooksIcon className="mr-1 size-4 shrink-0 text-[#999]" />
                            )
                        }
                        label={item.name}
                        onRemove={() => onRemoveKnowledge(item)}
                    />
                ))}
            </div>
        </div>
    );
}
