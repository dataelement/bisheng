/**
 * SyncSpaceItem — one row representing a bound knowledge-space/folder target
 * inside the channel ➜ knowledge space sync configuration list.
 *
 * Path rendering rules (per v2.5 Module D spec):
 *   • Knowledge-space-only binding: show just the space name (bold).
 *   • Folder binding: show `space / parent / parent / …` in grey + final
 *     segment in bold black. The knowledge-space name is always the first
 *     grey segment so users can see which space the folder belongs to.
 *
 * Deletion is immediate (no confirm dialog) per spec 3.1.4.
 */
import { BookCopyIcon, FolderClosedIcon } from "lucide-react";
import { useLocalize } from "~/hooks";
import type { KnowledgeSyncSpaceItem } from "~/api/channels";
import { ChannelNotebookOneIcon } from "~/components/icons/channels";

interface Props {
    space: KnowledgeSyncSpaceItem;
    onDelete: () => void;
}

export default function SyncSpaceItem({ space, onDelete }: Props) {
    const localize = useLocalize();
    const hasFolder = !!space.folder_path;
    let pathParents = "";
    let pathLeaf = space.knowledge_space_name || "";

    if (hasFolder) {
        const parts = (space.folder_path || "").split("/").filter(Boolean);
        pathLeaf = parts.pop() || "";
        const parents = [space.knowledge_space_name || "", ...parts].filter(Boolean);
        pathParents = parents.join(" / ");
    }

    return (
        <div className="flex items-center justify-between rounded-md px-2 py-1.5 text-[13px] hover:bg-[#F7F8FA]">
            <div className="flex min-w-0 items-center gap-1">
                {hasFolder ? (
                    <FolderClosedIcon className="size-4 shrink-0 text-[#86909C]" />
                ) : (
                    <ChannelNotebookOneIcon className="size-4 shrink-0 text-[#86909C]" />
                )}
                {hasFolder && pathParents && (
                    <span className="truncate text-[#86909C]" title={pathParents}>
                        {pathParents} /
                    </span>
                )}
                <span
                    className="truncate font-medium text-[#1D2129]"
                    title={pathLeaf}
                >
                    {pathLeaf || "—"}
                </span>
            </div>
            <button
                type="button"
                onClick={onDelete}
                className="shrink-0 px-1 text-[13px] text-[#86909C] hover:text-[#F53F3F]"
            >
                {localize?.("com_subscription.delete") || "删除"}
            </button>
        </div>
    );
}
