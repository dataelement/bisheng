/**
 * Attachment bar shown at the top of the chat input box once a knowledge space
 * or file is mounted. Figma 12841:46839.
 *
 * Layout: a full-bleed light-gray strip with rounded top corners, sitting above
 * the textarea inside the input box. Cards are a single non-wrapping row that
 * scrolls horizontally:
 *  - newest item appears leftmost (unified across files / knowledge spaces);
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
import { Loader2 } from "lucide-react";
import { Outlined } from "bisheng-icons";
import BookOpen from "~/components/ui/icon/BookOpen";
import BooksIcon from "~/components/ui/icon/Books";
import type { FileType } from "~/components/ui/icon/File/FileIcon";
import { cn } from "~/utils";

/** Fixed card geometry from the design (Figma 12841:47405). */
const CARD_WIDTH = 148;

// File-chip icons: flat bisheng outlined icons so they render in the same
// single-color (#999) style as the knowledge-space chip icons.
const CHIP_FILE_ICONS: Record<string, typeof Outlined.File> = {
    xls: Outlined.FileExcel,
    xlsx: Outlined.FileExcel,
    csv: Outlined.FileExcel,
    pdf: Outlined.FilePdf,
    ppt: Outlined.FilePdf,
    pptx: Outlined.FilePdf,
    txt: Outlined.FileTxt,
    doc: Outlined.FileWord,
    docx: Outlined.FileWord,
    png: Outlined.FileImage,
    jpg: Outlined.FileImage,
    jpeg: Outlined.FileImage,
    bmp: Outlined.FileImage,
    md: Outlined.FileEditing,
};

function resolveFileType(input: any): FileType {
    const nameCandidate =
        input?.name ||
        input?.file_name ||
        input?.filename ||
        input?.filepath ||
        input?.file_path ||
        "";
    const baseName = String(nameCandidate).split("/").pop()?.split("?")[0] || "";
    const ext = baseName.includes(".") ? baseName.split(".").pop()?.toLowerCase() : "";
    const normalized = ext === "htm" ? "html" : ext === "et" ? "xlsx" : ext === "jpeg" ? "jpg" : ext;
    const allowed: FileType[] = [
        "pdf", "doc", "docx", "ppt", "pptx", "md", "html", "txt",
        "jpg", "jpeg", "png", "bmp", "csv", "xls", "xlsx",
    ];
    return (allowed as string[]).includes(normalized || "") ? (normalized as FileType) : "txt";
}

/** Shared card shell: fixed width, white surface, optional hover-only remove. */
const CardShell = ({
    icon,
    label,
    title,
    onRemove,
}: {
    icon: React.ReactNode;
    label: string;
    title?: string;
    onRemove?: () => void;
}) => (
    <div
        className="group flex h-[30px] shrink-0 items-center gap-1 rounded-md bg-white px-2 text-xs text-[#212121]"
        style={{ width: CARD_WIDTH }}
    >
        <span className="flex size-4 shrink-0 items-center justify-center text-[#999]">{icon}</span>
        <span className="min-w-0 flex-1 truncate text-left" title={title ?? label}>
            {label}
        </span>
        {onRemove && (
            <button
                type="button"
                onClick={onRemove}
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
    const FileTypeIcon = CHIP_FILE_ICONS[resolveFileType(file)] ?? Outlined.File;
    return (
        <CardShell
            icon={<FileTypeIcon size={16} />}
            label={file.name}
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

const UploadingCard = ({ name }: { name: string }) => (
    <CardShell icon={<Loader2 className="size-4 animate-spin" />} label={name} />
);

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
                "flex size-4 shrink-0 items-center justify-center text-[#666] transition-colors hover:text-[#212121]",
                direction === "left" ? "ml-2" : "mr-2",
            )}
        >
            <Icon size={16} />
        </button>
    );
};

interface AttachmentBarProps {
    uploadingFiles: Array<{ id: string; name: string }>;
    files: any[];
    kbs: any[];
    skills: any[];
    onRemoveFile?: (file: any) => void;
    onRemoveKb?: (kb: any) => void;
    onRemoveSkill?: (skill: any) => void;
}

type Entry =
    | { kind: "uploading"; key: string; data: { id: string; name: string } }
    | { kind: "file"; key: string; data: any }
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
    // Insertion sequence per item key so the row can show newest-first across
    // all types (files + knowledge spaces) without timestamps on the data.
    const seqRef = useRef<{ map: Map<string, number>; n: number }>({ map: new Map(), n: 0 });
    const [canLeft, setCanLeft] = useState(false);
    const [canRight, setCanRight] = useState(false);

    const entries = useMemo<Entry[]>(() => {
        const all: Entry[] = [
            ...uploadingFiles.map((f) => ({ kind: "uploading" as const, key: `up-${f.id}`, data: f })),
            ...files.map((f) => ({ kind: "file" as const, key: `file-${f.file_id || f.filepath || f.name}`, data: f })),
            ...kbs.map((k) => ({ kind: "kb" as const, key: `kb-${k.id}`, data: k })),
            ...skills.map((s) => ({ kind: "skill" as const, key: `skill-${s.name}`, data: s })),
        ];
        const { map } = seqRef.current;
        for (const it of all) {
            if (!map.has(it.key)) map.set(it.key, seqRef.current.n++);
        }
        // Newest (highest sequence) first → leftmost.
        return all.sort((a, b) => (map.get(b.key) ?? 0) - (map.get(a.key) ?? 0));
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

    // Keep the newest (leftmost) item in view whenever a new front item arrives.
    const frontKey = entries[0]?.key;
    useEffect(() => {
        scrollRef.current?.scrollTo({ left: 0 });
    }, [frontKey]);

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
        <div className="relative -mb-4 w-full overflow-hidden rounded-t-2xl bg-[rgba(244,244,244,0.55)] px-2 pb-6 pt-2">
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
                                    return <UploadingCard key={entry.key} name={entry.data.name} />;
                                case "file":
                                    return (
                                        <FileCard
                                            key={entry.key}
                                            file={entry.data}
                                            onRemove={onRemoveFile ? () => onRemoveFile(entry.data) : undefined}
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
                            "pointer-events-none absolute left-0 top-0 h-full w-6 bg-gradient-to-r from-[#f9f9f9] from-[49%] to-transparent transition-opacity",
                            canLeft ? "opacity-100" : "opacity-0",
                        )}
                    />
                    {/* Right-edge fade hinting at hidden overflow (Figma gradient). */}
                    <div
                        className={cn(
                            "pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-[#f9f9f9] from-[49%] to-transparent transition-opacity",
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
