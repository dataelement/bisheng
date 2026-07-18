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
import { ExpandableSearchField } from "~/components/ui/ExpandableSearchField";
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
    spaceId: string | null;
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

function findSpaceInCategories(categories: CategoryGroup[], spaceId: string | null) {
    if (!spaceId) return undefined;
    for (const category of categories) {
        const space = category.spaces.find((item) => item.id === spaceId);
        if (space) return space;
    }
    return undefined;
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
                        <Outlined.Down className="size-3.5 text-[#8D93A0]" />
                    ) : (
                        <Outlined.Right className="size-3.5 text-[#8D93A0]" />
                    )}
                </button>

                <div className="flex size-5 shrink-0 items-center justify-center">
                    {category === "department" ? (
                        <Outlined.City className={cn("size-3.5", rootSelected ? "text-[#1d2129]" : "text-[#86909C]")} />
                    ) : (
                        <Outlined.Notebook className={cn("size-3.5", rootSelected ? "text-[#1d2129]" : "text-[#86909C]")} />
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
    const [selection, setSelection] = useState<Selection>({ spaceId: null, folderId: null });
    const [expandedSpaces, setExpandedSpaces] = useState<Set<string>>(() => new Set());
    const [collapsedCategories, setCollapsedCategories] = useState<Set<CategoryKey>>(() => new Set());

    // Scroll-following ellipsis for the tree names (mirrors the sidebar): names
    // extend to their natural width so the panel scrolls horizontally, while the
    // visible ellipsis tracks the viewport's right edge as you scroll.
    const treeScrollRef = useRef<HTMLDivElement>(null);
    // Re-attach when the dialog opens — Radix only mounts the container then.
    useDynamicEllipsis(treeScrollRef, [open]);

    const crossSpace = selection.spaceId != null && selection.spaceId !== currentSpaceId;

    // Reset on every open; the permission-filtered tree selects the first valid space below.
    useEffect(() => {
        if (open) {
            setSearch("");
            setSelection({ spaceId: null, folderId: null });
            setExpandedSpaces(new Set());
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

    useEffect(() => {
        if (!open) return;

        const selectedSpace = findSpaceInCategories(categories, selection.spaceId);
        if (selectedSpace) return;

        const defaultSpace = findSpaceInCategories(categories, currentSpaceId) ?? categories[0]?.spaces[0];
        if (!defaultSpace) {
            if (selection.spaceId !== null || selection.folderId !== null) {
                setSelection({ spaceId: null, folderId: null });
            }
            return;
        }

        setSelection({ spaceId: defaultSpace.id, folderId: null });
        setExpandedSpaces((prev) => {
            const next = new Set(prev);
            next.add(defaultSpace.id);
            return next;
        });
    }, [open, categories, currentSpaceId, selection.spaceId, selection.folderId]);

    // Flat lookup for selected-space metadata (role/name).
    const spaceById = useMemo(() => {
        const map = new Map<string, KnowledgeSpace>();
        for (const s of [...departmentSpaces, ...createdSpaces, ...joinedSpaces]) map.set(s.id, s);
        return map;
    }, [departmentSpaces, createdSpaces, joinedSpaces]);
    const selectedSpaceId = selection.spaceId;
    const selectedSpace = selectedSpaceId ? spaceById.get(selectedSpaceId) : undefined;

    // Right panel: contents (folders + files) of the selected location.
    const { data: children, isLoading } = useQuery({
        queryKey: ["move-children", selectedSpaceId, selection.folderId],
        queryFn: () => {
            if (!selectedSpaceId) {
                return Promise.resolve({ data: [], page_size: 200, has_more: false, next_cursor: null });
            }
            return getSpaceChildrenApi({
                space_id: selectedSpaceId,
                parent_id: selection.folderId ?? undefined,
                page_size: 200,
                file_status: statusFilterFor(selectedSpace),
            });
        },
        enabled: open && !!selectedSpaceId,
    });
    const items: KnowledgeFile[] = children?.data ?? [];
    const loadingChildren = !!selectedSpaceId && isLoading;
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
        setSelection((prev) => {
            if (!prev.spaceId) return prev;
            return { spaceId: prev.spaceId, folderId: folder.id, folderName: folder.name };
        });
    };

    const handleConfirm = () => {
        if (!selection.spaceId) return;
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
            {/* Mobile (≤768px): full-screen sheet, single-column tree (right panel
                hidden), full-width footer — mirrors the member-management dialog. */}
            <DialogContent
                className="flex max-w-3xl flex-col max-[768px]:fixed max-[768px]:inset-0 max-[768px]:h-[100dvh] max-[768px]:max-h-[100dvh] max-[768px]:w-full max-[768px]:max-w-none max-[768px]:translate-x-0 max-[768px]:translate-y-0 max-[768px]:gap-3 max-[768px]:rounded-none max-[768px]:p-4"
                onOpenAutoFocus={(e) => e.preventDefault()}
            >
                <DialogHeader className="text-left">
                    <DialogTitle>{localize("com_knowledge.move_to")}</DialogTitle>
                </DialogHeader>

                <div className="flex h-[420px] overflow-hidden rounded-lg border border-[#ececec] max-[768px]:h-auto max-[768px]:min-h-0 max-[768px]:flex-1 max-[768px]:rounded-none max-[768px]:border-0">
                    {/* Left: categorized space + folder tree */}
                    <div className="flex w-72 shrink-0 flex-col border-r border-[#ececec] max-[768px]:w-full max-[768px]:border-r-0">
                        <div className="p-3 max-[768px]:px-0 max-[768px]:pt-0">
                            <ExpandableSearchField
                                alwaysExpanded
                                showClearButton
                                value={search}
                                onChange={setSearch}
                                placeholder={localize("com_knowledge.move_search_placeholder")}
                                expandedWidthClassName="w-full"
                                containerClassName="!rounded-md"
                            />
                        </div>

                        {/* overflow-auto + w-max wrapper → horizontal scroll for deep/long
                            names, mirroring the sidebar directory. scrollbar-os opts out of
                            the global custom scrollbar so the OS setting (auto-hide vs
                            always-on) is respected. */}
                        <div
                            ref={treeScrollRef}
                            className="scrollbar-os flex-1 overflow-auto px-2 pb-2 max-[768px]:rounded-md max-[768px]:border max-[768px]:border-[#ECECEC] max-[768px]:p-2"
                        >
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
                                                    className="group/cat flex cursor-pointer select-none items-center gap-1 px-2 py-1"
                                                    onClick={() => handleToggleCategory(cat.key)}
                                                >
                                                    <span className="whitespace-nowrap text-[12px] font-medium text-[#86909C] transition-colors group-hover/cat:text-[#4e5969]">
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

                    {/* Right: contents of the selected location — hidden on mobile,
                        where navigation/selection happens entirely in the left tree. */}
                    <div className="flex flex-1 flex-col max-[768px]:hidden">
                        {/* Row metrics mirror the left tree items: 28px (h-7) rows, 12px text,
                            16px icon in a 20px slot, p-2 container padding. */}
                        <div className="scrollbar-os flex-1 overflow-y-auto p-2">
                            {loadingChildren ? (
                                <div className="flex h-full items-center justify-center text-[#86909C]">
                                    <Loader2 className="size-5 animate-spin" />
                                </div>
                            ) : folders.length === 0 && files.length === 0 ? (
                                <div className="flex h-full items-center justify-center text-[12px] text-[#86909C]">
                                    {localize("com_knowledge.move_empty_folder")}
                                </div>
                            ) : (
                                <>
                                    {folders.map((f) => (
                                        <button
                                            key={f.id}
                                            type="button"
                                            onClick={() => handleEnterFolder(f)}
                                            className="flex h-7 w-full items-center rounded-md px-1 text-left text-[12px] leading-5 hover:bg-[#F4F4F4]"
                                        >
                                            <div className="flex size-5 shrink-0 items-center justify-center">
                                                <Outlined.FolderClose className="size-3.5 text-[#212121]" />
                                            </div>
                                            <span className="ml-0.5 min-w-0 flex-1 truncate text-[#212121]">{f.name}</span>
                                            <Outlined.Right className="size-3.5 shrink-0 text-[#C9CDD4]" />
                                        </button>
                                    ))}
                                    {/* Files are not move targets — greyed out, not selectable. */}
                                    {files.map((f) => {
                                        const Glyph = fileGlyph(f.name);
                                        return (
                                            <div
                                                key={f.id}
                                                className="flex h-7 w-full cursor-default items-center px-1 text-[12px] leading-5 text-[#999]"
                                            >
                                                <div className="flex size-5 shrink-0 items-center justify-center">
                                                    <Glyph className="size-3.5 text-[#999]" />
                                                </div>
                                                <span className="ml-0.5 min-w-0 flex-1 truncate">{f.name}</span>
                                            </div>
                                        );
                                    })}
                                </>
                            )}
                        </div>
                    </div>
                </div>

                {/* Mobile: keep the two buttons in a row — 取消 (left) / 移动到此 (right),
                    each filling half the width; height stays 32px. */}
                <DialogFooter className="max-[768px]:flex-row max-[768px]:gap-2">
                    <Button
                        variant="outline"
                        className="h-8 !rounded-md max-[768px]:flex-1"
                        onClick={() => onOpenChange(false)}
                    >
                        {localize("cancel")}
                    </Button>
                    <Button
                        className="h-8 !rounded-md max-[768px]:flex-1"
                        onClick={handleConfirm}
                        disabled={!selection.spaceId}
                    >
                        {localize("com_knowledge.move_here")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
