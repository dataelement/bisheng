import { useQuery } from "@tanstack/react-query";
import { Outlined } from "bisheng-icons";
import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
    FileType,
    getDepartmentSpacesApi,
    getJoinedSpacesApi,
    getMineSpacesApi,
    getSpaceChildrenApi,
    type KnowledgeFile,
    type KnowledgeSpace,
    SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED,
    SpaceRole,
} from "~/api/knowledge";
import { listUploadableSpacesApi } from "~/api/messageExport";
import { Button } from "~/components/ui/Button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { useDynamicEllipsis } from "../hooks/useDynamicEllipsis";
import { DynamicEllipsisName } from "../sidebar/DynamicEllipsisName";
import { MoveToFolderTree, type FolderSelectPayload } from "./MoveToFolderTree";

interface MoveToDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Source space — selected by default and labelled "current". */
    currentSpaceId: string;
    currentSpaceName: string;
    /**
     * Resolve the chosen target and run the move. The dialog only picks a
     * destination; conflict/undo/confirm handling lives in the caller (T011).
     * Returning a promise keeps the button busy until the move settles.
     */
    onConfirm: (
        targetSpaceId: string,
        targetFolderId: string | null,
        crossSpace: boolean,
        targetFolderName?: string,
    ) => Promise<void> | void;
}

type CategoryKey = "department" | "created" | "joined";

interface CategoryGroup {
    key: CategoryKey;
    label: string;
    spaces: KnowledgeSpace[];
}

/** Local selection: a space root (folderId=null) or a folder inside it. */
interface Selection {
    spaceId: string;
    folderId: string | null;
    folderName?: string;
}

/** MEMBER-role users hide FAILED items; admins/creators see everything. */
function statusFilterFor(space?: KnowledgeSpace): number[] | undefined {
    return space?.role === SpaceRole.MEMBER ? SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED : undefined;
}

const IMAGE_EXTENSIONS = ["png", "jpg", "jpeg", "bmp", "gif", "webp"];

/** Right-panel file glyph — mirrors the table-mode icon (FileTable.tsx). */
function fileGlyph(name: string) {
    const ext = name.split(".").pop()?.toLowerCase() || "";
    return IMAGE_EXTENSIONS.includes(ext) ? Outlined.FileImage : Outlined.File;
}

// ─── Space row (left tree, 1st level) ─────────────────────────────────────────

interface SpaceRowProps {
    space: KnowledgeSpace;
    category: CategoryKey;
    isCurrent: boolean;
    expanded: boolean;
    selection: Selection;
    onToggleExpand: (spaceId: string) => void;
    onSelectSpace: (space: KnowledgeSpace) => void;
    onSelectFolder: (space: KnowledgeSpace, folder: FolderSelectPayload) => void;
}

function SpaceRow({
    space,
    category,
    isCurrent,
    expanded,
    selection,
    onToggleExpand,
    onSelectSpace,
    onSelectFolder,
}: SpaceRowProps) {
    const localize = useLocalize();
    // The space row is "selected" only when its own root is the target (no folder).
    const rootSelected = selection.spaceId === space.id && selection.folderId == null;
    const fileStatus = statusFilterFor(space);

    return (
        <div className="flex flex-col gap-0.5">
            <div
                className={cn(
                    "group flex h-7 cursor-pointer select-none items-center rounded-md pr-1 text-[12px] leading-5 text-[#1d2129] transition-colors hover:bg-[#F4F4F4]",
                    rootSelected && "bg-[#EEEEEE] font-semibold hover:bg-[#EEEEEE]",
                )}
                onClick={() => onSelectSpace(space)}
            >
                <button
                    type="button"
                    className="flex size-5 shrink-0 items-center justify-center"
                    onClick={(e) => {
                        e.stopPropagation();
                        onToggleExpand(space.id);
                    }}
                    aria-label={expanded ? "Collapse space" : "Expand space"}
                >
                    {expanded ? (
                        <Outlined.Down className="size-4 text-[#8D93A0]" />
                    ) : (
                        <Outlined.Right className="size-4 text-[#8D93A0]" />
                    )}
                </button>

                <div className="flex size-5 shrink-0 items-center justify-center">
                    {category === "department" ? (
                        <Outlined.City className={cn("size-4", rootSelected ? "text-[#1d2129]" : "text-[#86909C]")} />
                    ) : (
                        <Outlined.Notebook className={cn("size-4", rootSelected ? "text-[#1d2129]" : "text-[#86909C]")} />
                    )}
                </div>

                <DynamicEllipsisName
                    name={space.name}
                    textClassName={cn("text-[12px] leading-5 text-[#1d2129]", rootSelected && "font-semibold")}
                    trailing={
                        isCurrent ? (
                            <span className="shrink-0 whitespace-nowrap text-[12px] text-[#86909C]">
                                {localize("com_knowledge.current_space_tag")}
                            </span>
                        ) : null
                    }
                />
            </div>

            {/* Folder subtree — indent past the space row's chevron + icon (40px). */}
            {expanded && (
                <MoveToFolderTree
                    knowledgeId={space.id}
                    selectedFolderId={selection.spaceId === space.id ? selection.folderId : null}
                    fileStatus={fileStatus}
                    onSelectFolder={(folder) => onSelectFolder(space, folder)}
                    baseIndent={20}
                />
            )}
        </div>
    );
}

// ─── Dialog ───────────────────────────────────────────────────────────────────

export function MoveToDialog({
    open,
    onOpenChange,
    currentSpaceId,
    onConfirm,
}: MoveToDialogProps) {
    const localize = useLocalize();
    const [search, setSearch] = useState("");
    const [selection, setSelection] = useState<Selection>({ spaceId: currentSpaceId, folderId: null });
    const [expandedSpaces, setExpandedSpaces] = useState<Set<string>>(() => new Set([currentSpaceId]));
    const [collapsedCategories, setCollapsedCategories] = useState<Set<CategoryKey>>(() => new Set());

    // Scroll-following ellipsis for the tree names (mirrors the sidebar): names
    // extend to their natural width so the panel scrolls horizontally, while the
    // visible ellipsis tracks the viewport's right edge as you scroll.
    const treeScrollRef = useRef<HTMLDivElement>(null);
    useDynamicEllipsis(treeScrollRef);

    const crossSpace = selection.spaceId !== currentSpaceId;

    // Reset to the source space root on every open.
    useEffect(() => {
        if (open) {
            setSearch("");
            setSelection({ spaceId: currentSpaceId, folderId: null });
            setExpandedSpaces(new Set([currentSpaceId]));
            setCollapsedCategories(new Set());
        }
    }, [open, currentSpaceId]);

    const handleToggleCategory = (key: CategoryKey) => {
        setCollapsedCategories((prev) => {
            const next = new Set(prev);
            next.has(key) ? next.delete(key) : next.add(key);
            return next;
        });
    };

    // Permission whitelist: only spaces the user can upload (= move) into.
    const { data: uploadable = [] } = useQuery({
        queryKey: ["move-uploadable-spaces"],
        queryFn: () => listUploadableSpacesApi(),
        enabled: open,
    });
    const { data: departmentSpaces = [] } = useQuery({
        queryKey: ["move-spaces", "department"],
        queryFn: () => getDepartmentSpacesApi(),
        enabled: open,
    });
    const { data: createdSpaces = [] } = useQuery({
        queryKey: ["move-spaces", "mine"],
        queryFn: () => getMineSpacesApi(),
        enabled: open,
    });
    const { data: joinedSpaces = [] } = useQuery({
        queryKey: ["move-spaces", "joined"],
        queryFn: () => getJoinedSpacesApi(),
        enabled: open,
    });

    // Categorized, permission-filtered, name-searched tree source.
    const categories = useMemo<CategoryGroup[]>(() => {
        const allowed = new Set(uploadable.map((s) => s.id));
        const kw = search.trim().toLowerCase();
        const refine = (list: KnowledgeSpace[]) =>
            list.filter((s) => allowed.has(s.id) && (!kw || s.name.toLowerCase().includes(kw)));
        return [
            { key: "department" as const, label: localize("com_knowledge.department_spaces"), spaces: refine(departmentSpaces) },
            { key: "created" as const, label: localize("com_knowledge.created_by_me"), spaces: refine(createdSpaces) },
            { key: "joined" as const, label: localize("com_knowledge.joined_by_me"), spaces: refine(joinedSpaces) },
        ].filter((c) => c.spaces.length > 0);
    }, [uploadable, departmentSpaces, createdSpaces, joinedSpaces, search, localize]);

    // Flat lookup for selected-space metadata (role/name).
    const spaceById = useMemo(() => {
        const map = new Map<string, KnowledgeSpace>();
        for (const s of [...departmentSpaces, ...createdSpaces, ...joinedSpaces]) map.set(s.id, s);
        return map;
    }, [departmentSpaces, createdSpaces, joinedSpaces]);
    const selectedSpace = spaceById.get(selection.spaceId);

    // Right panel: contents (folders + files) of the selected location.
    const { data: children, isLoading } = useQuery({
        queryKey: ["move-children", selection.spaceId, selection.folderId],
        queryFn: () =>
            getSpaceChildrenApi({
                space_id: selection.spaceId,
                parent_id: selection.folderId ?? undefined,
                page_size: 200,
                file_status: statusFilterFor(selectedSpace),
            }),
        enabled: open && !!selection.spaceId,
    });
    const items: KnowledgeFile[] = children?.data ?? [];
    const folders = items.filter((it) => it.type === FileType.FOLDER);
    const files = items.filter((it) => it.type !== FileType.FOLDER);

    const handleToggleExpand = (spaceId: string) => {
        setExpandedSpaces((prev) => {
            const next = new Set(prev);
            next.has(spaceId) ? next.delete(spaceId) : next.add(spaceId);
            return next;
        });
    };

    const handleSelectSpace = (space: KnowledgeSpace) => {
        setSelection({ spaceId: space.id, folderId: null });
    };

    const handleSelectFolder = (space: KnowledgeSpace, folder: FolderSelectPayload) => {
        setSelection({ spaceId: space.id, folderId: folder.id, folderName: folder.name });
    };

    // Right-panel folder click drills into that folder (same space).
    const handleEnterFolder = (folder: KnowledgeFile) => {
        setSelection((prev) => ({ spaceId: prev.spaceId, folderId: folder.id, folderName: folder.name }));
    };

    const handleConfirm = () => {
        // Close the picker BEFORE running the move. executeMove shows its own
        // feedback (cross-space confirm, partial "move the rest" dialog, toasts);
        // if this Radix Dialog were still open it would aria-hide / disable those
        // nested layers and hide toasts behind its overlay.
        const targetFolderName = selection.folderId ? selection.folderName : undefined;
        onOpenChange(false);
        Promise.resolve(onConfirm(selection.spaceId, selection.folderId, crossSpace, targetFolderName)).catch(() => {});
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle>{localize("com_knowledge.move_to")}</DialogTitle>
                </DialogHeader>

                <div className="flex h-[420px] overflow-hidden rounded-lg border border-[#ececec]">
                    {/* Left: categorized space + folder tree */}
                    <div className="flex w-72 shrink-0 flex-col border-r border-[#ececec]">
                        <div className="border-b border-[#ececec] p-3">
                            <div className="flex items-center gap-2 rounded-lg border border-[#ececec] px-3 py-1.5">
                                <Outlined.Search className="size-4 shrink-0 text-[#818181]" />
                                <input
                                    value={search}
                                    onChange={(e) => setSearch(e.target.value)}
                                    placeholder={localize("com_knowledge.move_search_placeholder")}
                                    className="min-w-0 flex-1 bg-transparent text-[14px] leading-[22px] text-[#212121] outline-none placeholder:text-[#818181]"
                                />
                            </div>
                        </div>

                        {/* overflow-auto + w-max wrapper → horizontal scroll for deep/long
                            names, mirroring the sidebar directory. */}
                        <div ref={treeScrollRef} className="flex-1 overflow-auto p-2">
                            {categories.length === 0 ? (
                                <div className="flex h-full items-center justify-center px-3 text-center text-[12px] text-[#86909C]">
                                    {localize("com_knowledge.move_no_spaces")}
                                </div>
                            ) : (
                                <div className="w-max min-w-full">
                                    {categories.map((cat) => {
                                        const catCollapsed = collapsedCategories.has(cat.key);
                                        return (
                                            <div key={cat.key} className="mb-2 last:mb-0">
                                                <div
                                                    className="group/cat flex cursor-pointer select-none items-center gap-1 rounded-md px-2 py-1 hover:bg-[#F4F4F4]"
                                                    onClick={() => handleToggleCategory(cat.key)}
                                                >
                                                    <span className="whitespace-nowrap text-[12px] font-medium text-[#86909C]">
                                                        {cat.label}
                                                    </span>
                                                    {/* Collapse toggle sits to the RIGHT of the label, revealed on
                                                        hover (and kept visible while collapsed). */}
                                                    <Outlined.Down
                                                        className={cn(
                                                            "size-3.5 text-[#86909C] transition-all duration-150",
                                                            catCollapsed
                                                                ? "-rotate-90 opacity-100"
                                                                : "rotate-0 opacity-0 group-hover/cat:opacity-100",
                                                        )}
                                                    />
                                                </div>
                                                {!catCollapsed && (
                                                    <div className="flex flex-col gap-0.5">
                                                        {cat.spaces.map((space) => (
                                                            <SpaceRow
                                                                key={space.id}
                                                                space={space}
                                                                category={cat.key}
                                                                isCurrent={space.id === currentSpaceId}
                                                                expanded={expandedSpaces.has(space.id)}
                                                                selection={selection}
                                                                onToggleExpand={handleToggleExpand}
                                                                onSelectSpace={handleSelectSpace}
                                                                onSelectFolder={handleSelectFolder}
                                                            />
                                                        ))}
                                                    </div>
                                                )}
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Right: contents of the selected location */}
                    <div className="flex flex-1 flex-col">
                        <div className="flex-1 overflow-y-auto py-1">
                            {isLoading ? (
                                <div className="flex h-full items-center justify-center text-[#86909C]">
                                    <Loader2 className="size-5 animate-spin" />
                                </div>
                            ) : folders.length === 0 && files.length === 0 ? (
                                <div className="flex h-full items-center justify-center text-[14px] text-[#86909C]">
                                    {localize("com_knowledge.move_empty_folder")}
                                </div>
                            ) : (
                                <>
                                    {folders.map((f) => (
                                        <button
                                            key={f.id}
                                            type="button"
                                            onClick={() => handleEnterFolder(f)}
                                            className="flex w-full items-center gap-2 px-4 py-2 text-left text-[14px] hover:bg-[#F4F4F4]"
                                        >
                                            <Outlined.FolderClose className="size-4 shrink-0 text-[#8D93A0]" />
                                            <span className="flex-1 truncate text-[#212121]">{f.name}</span>
                                            <Outlined.Right className="size-4 shrink-0 text-[#C9CDD4]" />
                                        </button>
                                    ))}
                                    {/* Files are not move targets — greyed out, not selectable. */}
                                    {files.map((f) => {
                                        const Glyph = fileGlyph(f.name);
                                        return (
                                            <div
                                                key={f.id}
                                                className="flex w-full cursor-default items-center gap-2 px-4 py-2 text-[14px] text-[#999]"
                                            >
                                                <Glyph className="size-4 shrink-0 text-[#999]" />
                                                <span className="flex-1 truncate">{f.name}</span>
                                            </div>
                                        );
                                    })}
                                </>
                            )}
                        </div>
                    </div>
                </div>

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)}>
                        {localize("cancel")}
                    </Button>
                    <Button onClick={handleConfirm}>{localize("com_knowledge.move_here")}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
