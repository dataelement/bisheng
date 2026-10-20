/** Native-style attachment rail. References are owned by the writing area. */
import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useMemo,
    useRef,
    useState,
} from "react";
import { Outlined } from "bisheng-icons";
import { OGDialog, OGDialogContent } from "~/components/ui";
import { cn } from "~/utils";
import { formatBytes } from "~/utils/files";
import { isMediaChipFile, MediaAttachmentChip } from "~/components/Chat/attachments/MediaAttachmentChip";
import { ContextResourceCard } from "./ContextResourceCard";
import { Loader2 } from "lucide-react";
import { isMediaAttachmentFile } from "~/utils/mediaAttachmentUtils";
import { resolveKnowledgePreviewUrl } from "~/pages/knowledge/FilePreview/previewUrlUtils";
import { groupAttachmentsByFolder } from "~/components/Linsight/Input/ContextChips";
import { useLocalize } from "~/hooks";
import { FileIcon, getFileTypebyFileName } from "~/components/ui/icon/File/FileIcon";

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

const FileCard = ({ file, onRemove }: { file: any; onRemove?: () => void }) => {
    const fileName = file.name || file.file_name || file.filename || 'File';
    const [previewOpen, setPreviewOpen] = useState(false);

    if (isMediaChipFile({ ...file, name: fileName })) {
        return (
            <MediaAttachmentChip
                file={{ ...file, name: fileName }}
                onRemove={onRemove}
                variant="resource"
            />
        );
    }

    const previewUrl = resolveFilePreviewUrl(file);
    const isImagePreview = !!previewUrl && /\.(png|jpe?g|bmp|gif|webp)$/i.test(fileName);

    return (
        <>
            <ContextResourceCard
                label={fileName}
                description={[fileName.split('.').pop()?.toUpperCase(), Number(file.size) >= 0 ? formatBytes(Number(file.size), 1, true) : ''].filter(Boolean).join(' · ')}
                thumbnail={isImagePreview}
                icon={isImagePreview ? <img src={previewUrl} alt="" /> : <FileIcon type={getFileTypebyFileName(fileName) || "txt"} className="dsh-file-icon" />}
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
        <ContextResourceCard
            icon={<Outlined.FolderClose size={16} />}
            label={label}
            title={label}
            onRemove={onRemove}
        />
    );
};

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
                variant="resource"
            />
        );
    }
    return (
        <ContextResourceCard label={name} icon={<Loader2 className="size-6 animate-spin" />}
            onRemove={onRemove} />
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
                "dsh-attachment-arrow",
                direction === "left" ? "dsh-attachment-arrow-left" : "dsh-attachment-arrow-right",
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
    onRemoveFile?: (file: any) => void;
}

type Entry =
    | { kind: "uploading"; key: string; data: AttachmentBarProps['uploadingFiles'][number] }
    | { kind: "file"; key: string; data: any }
    | { kind: "folder"; key: string; data: { folderName: string; files: unknown[]; isUploading: boolean } };

export const AttachmentBar = ({
    uploadingFiles,
    files,
    onRemoveFile,
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

        const all: Entry[] = fileEntries;
        const { map } = seqRef.current;
        for (const it of all) {
            if (!map.has(it.key)) map.set(it.key, seqRef.current.n++);
        }
        // Oldest (lowest sequence) first → leftmost; newest appended on the right.
        return all.sort((a, b) => (map.get(a.key) ?? 0) - (map.get(b.key) ?? 0));
    }, [uploadingFiles, files]);

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
        <div className="dsh-composer-attachments w-full">
            <div className="relative flex items-center">
                {canLeft && <ArrowButton direction="left" onClick={() => pageScroll("left")} />}
                <div className="relative min-w-0 flex-1">
                    <div
                        ref={scrollRef}
                        onScroll={updateEdges}
                        className="dsh-attachment-rail flex overflow-x-auto [&::-webkit-scrollbar]:hidden"
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
                            }
                        })}
                    </div>
                    {/* Left-edge fade hinting at content scrolled off to the left. */}
                    <div
                        className={cn(
                            "pointer-events-none absolute left-0 top-0 h-full w-6 bg-gradient-to-r from-[rgb(var(--dsh-composer-bg,255_255_255))] from-[49%] to-transparent transition-opacity",
                            canLeft ? "opacity-100" : "opacity-0",
                        )}
                    />
                    {/* Right-edge fade hinting at hidden overflow (Figma gradient). */}
                    <div
                        className={cn(
                            "pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-[rgb(var(--dsh-composer-bg,255_255_255))] from-[49%] to-transparent transition-opacity",
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
