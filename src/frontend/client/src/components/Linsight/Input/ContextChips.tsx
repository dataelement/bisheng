/**
 * F035 Track H: chip row above the textarea (spec §1, fig.7). Shows the
 * current task context — selected skills, knowledge spaces / org KBs and
 * attached files — each removable via "x". Tools never produce chips.
 */
import { Loader2, Paperclip, Sparkles, X } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import BookOpen from '~/components/ui/icon/BookOpen';
import BooksIcon from '~/components/ui/icon/Books';
import { useLocalize } from '~/hooks';
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
    /** Folder upload: path relative to the picked folder, e.g. `年报/2024/Q1.xlsx`. */
    relative_path?: string;
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

export interface AttachmentGroup<T extends ContextAttachmentFile = ContextAttachmentFile> {
    key: string;
    /** Root directory of a folder upload; undefined for a loose file. */
    folderName?: string;
    files: T[];
    isUploading: boolean;
}

/**
 * Collapse each uploaded folder into a single group keyed by its ROOT directory.
 *
 * A folder upload is capped at 100 files; rendering one chip each would bury the
 * textarea and make "remove this folder" a hundred clicks. Loose files keep
 * their own chip so single-file behaviour is unchanged.
 */
export function groupAttachmentsByFolder<T extends ContextAttachmentFile>(files: T[]): AttachmentGroup<T>[] {
    const groups: AttachmentGroup<T>[] = [];
    const byFolder = new Map<string, AttachmentGroup<T>>();

    for (const file of files) {
        const root = (file.relative_path || '').split('/')[0];
        // A relative_path with no separator is a loose file, not a folder.
        const isInFolder = !!root && (file.relative_path || '').includes('/');
        if (!isInFolder) {
            groups.push({ key: `att-${file.clientId}`, files: [file], isUploading: !!file.isUploading });
            continue;
        }
        const existing = byFolder.get(root);
        if (existing) {
            existing.files.push(file);
            existing.isUploading = existing.isUploading || !!file.isUploading;
            continue;
        }
        const group: AttachmentGroup<T> = {
            key: `folder-${root}`,
            folderName: root,
            files: [file],
            isUploading: !!file.isUploading,
        };
        byFolder.set(root, group);
        groups.push(group);
    }
    return groups;
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
    <div className="group flex h-6 min-w-0 max-w-[160px] shrink-0 items-center rounded-sm bg-white px-2 text-xs text-slate-700 transition-colors duration-200 hover:bg-slate-50">
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
    const localize = useLocalize();
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

    // A 100-file folder must not become 100 chips. Collapse each uploaded folder
    // to one chip named after its root directory; loose files stay individual.
    const groups = groupAttachmentsByFolder(orderedFiles);

    return (
        <div className="mb-2 max-h-[72px] overflow-y-auto">
            <div className="flex flex-wrap gap-1">
                {groups.map((group) => (
                    <Chip
                        key={group.key}
                        icon={
                            group.isUploading ? (
                                <Loader2 className="mr-1 size-4 shrink-0 animate-spin text-[#999]" />
                            ) : group.folderName ? (
                                <Outlined.FolderClose size={16} className="mr-1 shrink-0 text-[#999]" />
                            ) : (
                                <Paperclip className="mr-1 size-4 shrink-0 text-[#999]" />
                            )
                        }
                        label={
                            group.folderName
                                ? `${group.folderName} (${localize('com_folder_upload_file_count', { 0: group.files.length })})`
                                : group.files[0].name
                        }
                        onRemove={
                            group.isUploading
                                ? undefined
                                : () => group.files.forEach((file) => onRemoveFile(file))
                        }
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
