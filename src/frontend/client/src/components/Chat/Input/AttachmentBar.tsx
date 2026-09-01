/**
 * Attachment bar shown at the top of the chat input box once a knowledge space
 * or file is mounted. Figma 12841:46839.
 *
 * Layout: a full-bleed light-gray strip with rounded top corners, sitting above
 * the textarea inside the input box. Cards are a single non-wrapping row that
 * scrolls horizontally:
 *  - items appear in insertion order (oldest left, newest right);
 *  - mouse wheel scrolls the row horizontally;
 *  - left / right chevron buttons page-scroll (one viewport per click) and only
 *    occupy width while their direction has more content — at an edge the arrow
 *    disappears and the cards sit flush;
 *  - a right-edge gradient hints at hidden overflow.
 */
import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { Outlined } from "bisheng-icons";
import BookOpen from "~/components/ui/icon/BookOpen";
import BooksIcon from "~/components/ui/icon/Books";
import { OGDialog, OGDialogContent } from "~/components/ui";
import { cn } from "~/utils";
import { isMediaChipFile, MediaAttachmentChip } from "~/components/Chat/attachments/MediaAttachmentChip";
import { FileUploadThumbnail } from "~/components/Chat/attachments/UploadAttachmentThumbnail";
import { isMediaAttachmentFile } from "~/utils/mediaAttachmentUtils";
import { resolveKnowledgePreviewUrl } from "~/pages/knowledge/FilePreview/previewUrlUtils";
import { groupAttachmentsByFolder } from "~/components/Linsight/Input/ContextChips";
import { useLocalize } from "~/hooks";

/** Fixed card geometry from the design (Figma 12841:47405). */
const CARD_WIDTH = 148;

/** Stable sequence key for a file attachment across upload → completed transition. */
function attachmentSeqKey(clientId: string | undefined): string | undefined {
    return clientId ? `att-${clientId}` : undefined;
}


function resolveFilePreviewUrl(file: {
    name?: string;
    previewUrl?: string;
    filepath?: string;
    file_path?: string;
    file_url?: string;
    url?: string;
}): string | undefined {
    if (file.previewUrl) return file.previewUrl;
    const remote = file.filepath || file.file_path || file.file_url || file.url;
    if (!remote || remote.startsWith('blob:')) return undefined;
    return resolveKnowledgePreviewUrl(remote);
}

/**
 * Icon for a file chip, picked from the file name's extension.
 * Exported so other surfaces that show the same chip (knowledge-space quick Q&A)
 * render identical icons instead of maintaining a second mapping.
 */
export const AttachmentFileIcon = ({ name }: { name: string }) => {
    const Icon = CHIP_FILE_ICONS[resolveFileType({ name })] ?? Outlined.File;
    return <Icon size={16} />;
};

/** Shared card shell: fixed width, white surface, optional hover-only remove. */
const CardShell = ({
    icon,
    label,
    title,
    onRemove,
    onClick,
    className,
}: {
    icon: React.ReactNode;
    label: string;
    title?: string;
    onRemove?: () => void;
    onClick?: () => void;
    /** Surface override — the chip is white on this bar's grey strip, but reused on
     *  white surfaces elsewhere, where it needs the inverse. Geometry stays fixed. */
    className?: string;
}) => (
    <div
        className={cn(
            "group flex h-[30px] shrink-0 items-center gap-1 rounded-md bg-white px-2 text-xs text-text-1",
            onClick && "cursor-pointer",
            className,
        )}
        style={{ width: CARD_WIDTH }}
        onClick={onClick}
    >
        <span className="flex size-4 shrink-0 items-center justify-center text-text-3">{icon}</span>
        <span className="min-w-0 flex-1 truncate text-left" title={title ?? label}>
            {label}
        </span>
        {onRemove && (
            <button
                type="button"
                // Stop propagation so removing a card never triggers the card's
                // own click (e.g. opening the image preview).
                onClick={(e) => { e.stopPropagation(); onRemove(); }}
                // Hover-reveal on hover-capable pointers; always visible where the
                // pointer can't hover (touch) — gated by CSS hover capability, not
                // screen width, so a small-screen PC still gets the hover behaviour.
                className="hidden size-4 shrink-0 items-center justify-center rounded text-slate-400 transition-colors hover:text-slate-600 group-hover:flex coarse-pointer:flex"
                aria-label="Remove"
            >
                <Outlined.Close size={12} />
            </button>
        )}
    </div>
);

/** The chat-mode reference chip itself, for surfaces outside this bar. */
export const AttachmentChip = CardShell;

const KbCard = ({ kb, onRemove }: { kb: any; onRemove?: () => void }) => (
    <CardShell
        icon={kb.type === "space"
            ? <BookOpen className="size-4" />
            : <BooksIcon className="size-4" />}
        label={kb.name ?? ""}
        onRemove={onRemove}
    />
);

const FileCard = ({ file, onRemove }: { file: any; onRemove?: () => void }) => {
    const fileName = file.name || file.file_name || file.filename || 'File';

    if (isMediaChipFile({ ...file, name: fileName })) {
        return (
            <MediaAttachmentChip
                file={{ ...file, name: fileName }}
                onRemove={onRemove}
                variant="bar"
            />
        );
    }

    const previewUrl = resolveFilePreviewUrl(file);
    const [previewOpen, setPreviewOpen] = useState(false);
    const isImagePreview = !!previewUrl && /\.(png|jpe?g|bmp|gif|webp)$/i.test(fileName);

    return (
        <>
            <FileUploadThumbnail
                fileName={fileName}
                previewUrl={isImagePreview ? previewUrl : undefined}
                variant="bar"
                onRemove={onRemove}
                onClick={isImagePreview ? () => setPreviewOpen(true) : undefined}
            />
            {isImagePreview && (
                <OGDialog open={previewOpen} onOpenChange={setPreviewOpen}>
                    <OGDialogContent
                        showCloseButton={false}
                        className={cn("w-auto max-w-[92vw] overflow-hidden bg-transparent p-0 shadow-none")}
                        disableScroll={false}
                    >
                        <img
                            src={previewUrl}
                            alt={fileName}
                            className="max-h-[85vh] max-w-full rounded-md object-contain"
                        />
                    </OGDialogContent>
                </OGDialog>
            )}
        </>
    );
};

/** One card for a whole uploaded directory (see `groupAttachmentsByFolder`). */
const FolderCard = ({
    folderName,
    fileCount,
    onRemove,
}: {
    folderName: string;
    fileCount: number;
    onRemove?: () => void;
}) => {
    const localize = useLocalize();
    const label = `${folderName} (${localize('com_folder_upload_file_count', { 0: fileCount })})`;
    return (
        <CardShell
            icon={<Outlined.FolderClose size={16} />}
            label={label}
            title={label}
            onRemove={onRemove}
        />
    );
};

const SkillCard = ({ skill, onRemove }: { skill: any; onRemove?: () => void }) => (
    <CardShell
        icon={<Outlined.Skill size={16} className="text-blue-500" />}
        label={skill?.display_name || skill?.name || ""}
        onRemove={onRemove}
    />
);

const UploadingCard = ({
    name,
    file,
    onRemove,
}: {
    name: string;
    file?: any;
    onRemove?: () => void;
}) => {
    if (file && isMediaAttachmentFile({ name: file.name || name })) {
        return (
            <MediaAttachmentChip
                file={{ name, isUploading: true, ...file }}
                onRemove={onRemove}
                variant="bar"
            />
        );
    }
    return (
        <FileUploadThumbnail
            fileName={name}
            previewUrl={file?.previewUrl}
            variant="bar"
            isUploading
            onRemove={onRemove}
        />
    );
};

const ArrowButton = ({
    direction,
    onClick,
}: {
    direction: "left" | "right";
    onClick: () => void;
}) => {
    const Icon = direction === "left" ? Outlined.Left : Outlined.Right;
    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={direction === "left" ? "Scroll back" : "Scroll forward"}
            // 8px gap only on the outer side (strip edge); the side facing the cards
            // stays flush at 0.
            className={cn(
                "flex size-4 shrink-0 items-center justify-center text-[#666] transition-colors hover:text-text-1",
                direction === "left" ? "ml-2" : "mr-2",
            )}
        >
            <Icon size={16} />
        </button>
    );
};

interface AttachmentBarProps {
    uploadingFiles: Array<{
        id: string;
        clientId?: string;
        name: string;
        previewUrl?: string;
        mediaPreviewUrl?: string;
        mediaCoverUrl?: string;
        cover_filepath?: string;
        mediaDurationSec?: number;
        /** Folder upload: path relative to the picked folder root. */
        relative_path?: string;
    }>;
    files: any[];
    kbs: any[];
    skills: any[];
    onRemoveFile?: (file: any) => void;
    onRemoveKb?: (kb: any) => void;
    onRemoveSkill?: (skill: any) => void;
}

type Entry =
    | { kind: "uploading"; key: string; data: AttachmentBarProps['uploadingFiles'][number] }
    | { kind: "file"; key: string; data: any }
    | { kind: "folder"; key: string; data: { folderName: string; files: unknown[]; isUploading: boolean } }
    | { kind: "kb"; key: string; data: any }
    | { kind: "skill"; key: string; data: any };

export const AttachmentBar = ({
    uploadingFiles,
    files,
    kbs,
    skills,
    onRemoveFile,
    onRemoveKb,
    onRemoveSkill,
}: AttachmentBarProps) => {
    const scrollRef = useRef<HTMLDivElement>(null);
    // Insertion sequence per item key — oldest first, newest appended to the right.
    const seqRef = useRef<{ map: Map<string, number>; n: number }>({ map: new Map(), n: 0 });
    const [canLeft, setCanLeft] = useState(false);
    const [canRight, setCanRight] = useState(false);

    const entries = useMemo<Entry[]>(() => {
        // Match uploading→completed by client id, not by name: a folder upload
        // routinely carries the same file name in several subdirectories, and a
        // name-keyed set would hide sibling cards that are still uploading.
        const completedIds = new Set(
            files.map((f) => String(f.clientId ?? f.id ?? '')).filter(Boolean),
        );
        const activeUploads = uploadingFiles.filter(
            (f) => !completedIds.has(String(f.clientId ?? f.id ?? '')),
        );

        // Folder upload: one card per picked DIRECTORY. A folder is capped at 100
        // files, and a card each would turn this strip into a scroll marathon
        // where removing the folder costs a hundred clicks.
        const fileLike = [
            ...activeUploads.map((f) => ({
                clientId: String(f.clientId ?? f.id),
                name: f.name,
                isUploading: true,
                relative_path: f.relative_path,
                __kind: "uploading" as const,
                __data: f,
                __key: attachmentSeqKey(f.id) ?? `up-${f.id}`,
            })),
            ...files.map((f) => ({
                clientId: String(f.clientId ?? f.id ?? f.file_id ?? f.name),
                name: f.name || f.file_name || f.filename || '',
                isUploading: false,
                relative_path: f.relative_path,
                __kind: "file" as const,
                __data: f,
                __key: attachmentSeqKey(f.clientId || f.id) ?? `file-${f.file_id || f.filepath || f.name}`,
            })),
        ];

        const fileEntries: Entry[] = groupAttachmentsByFolder(fileLike).map((group) => {
            if (group.folderName) {
                return {
                    kind: "folder" as const,
                    key: `folder-${group.folderName}`,
                    data: {
                        folderName: group.folderName,
                        files: group.files.map((f) => f.__data),
                        isUploading: group.isUploading,
                    },
                };
            }
            const only = group.files[0];
            return only.__kind === "uploading"
                ? { kind: "uploading" as const, key: only.__key, data: only.__data }
                : { kind: "file" as const, key: only.__key, data: only.__data };
        });

        const all: Entry[] = [
            ...fileEntries,
            // Knowledge selections are stored newest-first (the picker prepends),
            // the opposite of the file arrays. Feed them in oldest-first so the
            // sequence below means the same thing for every source: without this,
            // a set that first appears all at once — restoring a conversation from
            // localStorage — hands the newest item the lowest sequence and the row
            // comes back reversed, even though picking them one by one is correct.
            ...[...kbs].reverse().map((k) => ({ kind: "kb" as const, key: `kb-${k.id}`, data: k })),
            ...skills.map((s) => ({ kind: "skill" as const, key: `skill-${s.name}`, data: s })),
        ];
        const { map } = seqRef.current;
        for (const it of all) {
            if (!map.has(it.key)) map.set(it.key, seqRef.current.n++);
        }
        // Oldest (lowest sequence) first → leftmost; newest appended on the right.
        return all.sort((a, b) => (map.get(a.key) ?? 0) - (map.get(b.key) ?? 0));
    }, [uploadingFiles, files, kbs, skills]);

    const updateEdges = useCallback(() => {
        const el = scrollRef.current;
        if (!el) return;
        const maxScroll = el.scrollWidth - el.clientWidth;
        setCanLeft(el.scrollLeft > 1);
        setCanRight(el.scrollLeft < maxScroll - 1);
    }, []);

    // Recompute affordances when the item set changes or the row resizes.
    useLayoutEffect(() => {
        updateEdges();
        const el = scrollRef.current;
        if (!el || typeof ResizeObserver === "undefined") return;
        const ro = new ResizeObserver(() => updateEdges());
        ro.observe(el);
        return () => ro.disconnect();
    }, [updateEdges, entries.length]);

    // Scroll to the newest (rightmost) item when a new attachment arrives.
    const backKey = entries[entries.length - 1]?.key;
    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        el.scrollTo({ left: el.scrollWidth, behavior: 'smooth' });
    }, [backKey]);

    // Native non-passive wheel listener so preventDefault actually works
    // (React's synthetic onWheel is passive and can't block page scroll).
    useEffect(() => {
        const el = scrollRef.current;
        if (!el) return;
        const onWheel = (e: WheelEvent) => {
            if (el.scrollWidth <= el.clientWidth) return;
            // Translate vertical wheel into horizontal scroll; keep native horizontal.
            const delta = Math.abs(e.deltaY) > Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
            if (delta === 0) return;
            e.preventDefault();
            el.scrollLeft += delta;
        };
        el.addEventListener("wheel", onWheel, { passive: false });
        return () => el.removeEventListener("wheel", onWheel);
    }, []);

    const pageScroll = useCallback((dir: "left" | "right") => {
        const el = scrollRef.current;
        if (!el) return;
        // One "page" ≈ one row of visible cards.
        el.scrollBy({ left: dir === "left" ? -el.clientWidth : el.clientWidth, behavior: "smooth" });
    }, []);

    return (
        <div className="w-full pb-2 mb-1">
            <div className="flex items-center">
                {canLeft && <ArrowButton direction="left" onClick={() => pageScroll("left")} />}
                <div className="relative min-w-0 flex-1">
                    <div
                        ref={scrollRef}
                        onScroll={updateEdges}
                        className="flex gap-2 overflow-x-auto [&::-webkit-scrollbar]:hidden"
                        style={{ scrollbarWidth: "none" }}
                    >
                        {entries.map((entry) => {
                            switch (entry.kind) {
                                case "uploading":
                                    return (
                                        <UploadingCard
                                            key={entry.key}
                                            name={entry.data.name}
                                            file={entry.data}
                                            onRemove={
                                                onRemoveFile
                                                    ? () => onRemoveFile(entry.data)
                                                    : undefined
                                            }
                                        />
                                    );
                                case "file":
                                    return (
                                        <FileCard
                                            key={entry.key}
                                            file={entry.data}
                                            onRemove={onRemoveFile ? () => onRemoveFile(entry.data) : undefined}
                                        />
                                    );
                                case "folder":
                                    return (
                                        <FolderCard
                                            key={entry.key}
                                            folderName={entry.data.folderName}
                                            fileCount={entry.data.files.length}
                                            onRemove={
                                                onRemoveFile && !entry.data.isUploading
                                                    ? () => entry.data.files.forEach((f) => onRemoveFile(f))
                                                    : undefined
                                            }
                                        />
                                    );
                                case "kb":
                                    return (
                                        <KbCard
                                            key={entry.key}
                                            kb={entry.data}
                                            onRemove={onRemoveKb ? () => onRemoveKb(entry.data) : undefined}
                                        />
                                    );
                                case "skill":
                                    return (
                                        <SkillCard
                                            key={entry.key}
                                            skill={entry.data}
                                            onRemove={onRemoveSkill ? () => onRemoveSkill(entry.data) : undefined}
                                        />
                                    );
                                default:
                                    return null;
                            }
                        })}
                    </div>
                    {/* Left-edge fade hinting at content scrolled off to the left. */}
                    <div
                        className={cn(
                            "pointer-events-none absolute left-0 top-0 h-full w-6 bg-gradient-to-r from-white from-[49%] to-transparent transition-opacity",
                            canLeft ? "opacity-100" : "opacity-0",
                        )}
                    />
                    {/* Right-edge fade hinting at hidden overflow (Figma gradient). */}
                    <div
                        className={cn(
                            "pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-white from-[49%] to-transparent transition-opacity",
                            canRight ? "opacity-100" : "opacity-0",
                        )}
                    />
                </div>
                {canRight && <ArrowButton direction="right" onClick={() => pageScroll("right")} />}
            </div>
        </div>
    );
};

AttachmentBar.displayName = "AttachmentBar";
