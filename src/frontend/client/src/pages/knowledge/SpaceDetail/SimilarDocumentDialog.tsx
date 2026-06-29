import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Link2, Loader2, Search, FileSearch } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Tooltip, TooltipTrigger, TooltipContent } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { useDebounce } from "~/hooks/Input";
import { useToastContext } from "~/Providers";
import { useConfirm } from "~/Providers";
import {
    getPendingSimilarFilesApi,
    dismissSimilarApi,
    getSimilarCandidatesApi,
    searchDocumentsApi,
    linkAsNewVersionApi,
    type PendingSimilarFileEntry,
    type SimilarCandidateEntry,
    type SearchableDocumentEntry,
    type LinkAsNewVersionResponse,
} from "~/api/knowledge";

// ─── Props ─────────────────────────────────────────────────────────────────────

interface SimilarDocumentDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    spaceId: number;
    /**
     * When provided (non-empty), the pending list is restricted to these file ids
     * (string ids matching KnowledgeFile.id). Used by the batch entry so the dialog
     * only shows the similar documents the user actually selected. When omitted/empty,
     * every pending similar file in the space is shown.
     */
    restrictToFileIds?: string[];
    /** Called after a file is linked or dismissed so parent can refetch file list */
    onProcessed?: () => void;
}

// ─── Pending file row (left column) ───────────────────────────────────────────

interface PendingFileRowProps {
    entry: PendingSimilarFileEntry;
    isSelected: boolean;
    onClick: () => void;
}

function PendingFileRow({ entry, isSelected, onClick }: PendingFileRowProps) {
    const localize = useLocalize();
    return (
        <button
            type="button"
            onClick={onClick}
            className={[
                "w-full text-left px-3 py-3 transition-colors rounded-[8px] flex items-start gap-2 mb-1",
                "hover:bg-[#f2f3f5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                isSelected ? "bg-[#F0F5FF]" : "bg-transparent",
            ].join(" ")}
        >
            <FileSearch className={["shrink-0 size-[14px] mt-0.5", isSelected ? "text-blue-500" : "text-[#4e5969]"].join(" ")} />
            <div className="flex-1 min-w-0">
                <Tooltip>
                    <TooltipTrigger asChild>
                        <p
                            className={[
                                "truncate text-[14px] font-medium leading-5",
                                isSelected ? "text-blue-500" : "text-[#1d2129]",
                            ].join(" ")}
                        >
                            {entry.file_name}
                        </p>
                    </TooltipTrigger>
                    <TooltipContent
                        noArrow
                        side="right"
                        className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-[12px] text-white"
                    >
                        {entry.file_name}
                    </TooltipContent>
                </Tooltip>
                <p className="mt-1 text-[12px] text-[#86909c]">
                    {localize("com_knowledge.version.pending_row_recommend_count", {
                        count: entry.candidate_count,
                    })}
                </p>
            </div>
        </button>
    );
}

// ─── Recommendation card (Section 2) ──────────────────────────────────────────

interface RecommendationCardProps {
    entry: SimilarCandidateEntry;
    disabled: boolean;
    onLink: (doc: { document_id: number; title: string }) => void;
}

function RecommendationCard({ entry, disabled, onLink }: RecommendationCardProps) {
    const localize = useLocalize();

    const uploadTimeDisplay = entry.primary_upload_time
        ? entry.primary_upload_time.replace("T", " ").slice(0, 16)
        : null;

    const versionLine = entry.doc_code
        ? `${entry.doc_code} · 当前主版本 V${entry.current_primary_version_no ?? 1}`
        : `当前主版本 V${entry.current_primary_version_no ?? 1}`;

    return (
        <div className="flex items-center justify-between gap-3 rounded-[8px] border border-[#EBECF0] bg-white px-4 py-3 hover:border-blue-500 hover:bg-[#F4F8FF] transition-colors group">
            <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2 mb-1">
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <p className="min-w-0 cursor-default truncate text-[14px] font-medium text-[#1d2129]">
                                {entry.title}
                            </p>
                        </TooltipTrigger>
                        <TooltipContent
                            noArrow
                            side="top"
                            className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-[12px] text-white"
                        >
                            {entry.title}
                        </TooltipContent>
                    </Tooltip>
                    <span className="shrink-0 rounded bg-[#FFF3E8] px-1.5 py-0.5 text-[12px] text-[#F76F44]">
                        {localize("com_knowledge.version.similarity_label")} {(entry.similarity * 100).toFixed(0)}%
                    </span>
                </div>
                <p className="text-[12px] text-[#86909c] mb-0.5">{versionLine}</p>
                {uploadTimeDisplay && (
                    <p className="text-[12px] text-[#86909c]">{entry.title} · {uploadTimeDisplay}</p>
                )}
            </div>
            <Button
                type="button"
                size="sm"
                disabled={disabled}
                onClick={() =>
                    onLink({ document_id: entry.target_document_id, title: entry.title })
                }
                className="h-8 shrink-0 rounded-[6px] bg-blue-500 px-4 text-[12px] text-white hover:bg-blue-400 btn-brand-primary"
            >
                <Link2 className="mr-1.5 size-4" />
                {localize("com_knowledge.version.btn_link_as_new_version")}
            </Button>
        </div>
    );
}

// ─── Search result row (Section 3) ────────────────────────────────────────────

interface SearchResultRowProps {
    entry: SearchableDocumentEntry;
    disabled: boolean;
    onLink: (doc: { document_id: number; title: string }) => void;
}

function SearchResultRow({ entry, disabled, onLink }: SearchResultRowProps) {
    const localize = useLocalize();
    return (
        <div className="flex items-center justify-between gap-3 border-b border-[#F2F3F5] px-3 py-2.5 last:border-b-0 hover:bg-[#FAFAFA]">
            <div className="min-w-0 flex-1">
                <p className="truncate text-sm text-[#1d2129]">{entry.title}</p>
                <div className="mt-0.5 flex items-center gap-2 text-xs text-[#86909c]">
                    <span>V{entry.current_primary_version_no}</span>
                    {entry.doc_code && <span>{entry.doc_code}</span>}
                    {entry.primary_uploader_name && <span>{entry.primary_uploader_name}</span>}
                </div>
            </div>
            <Button
                type="button"
                size="sm"
                disabled={disabled}
                onClick={() => onLink({ document_id: entry.document_id, title: entry.title })}
                className="h-7 shrink-0 rounded-[6px] bg-blue-500 px-3 text-xs text-white hover:bg-blue-400 btn-brand-primary"
            >
                <Link2 className="mr-1.5 size-3" />
                {localize("com_knowledge.version.btn_link_as_new_version")}
            </Button>
        </div>
    );
}

// ─── Right panel — inline 4-section layout ────────────────────────────────────

interface RightPanelProps {
    spaceId: number;
    selectedFile: PendingSimilarFileEntry;
    dismissPending: boolean;
    onDismiss: () => void;
    onLinked: (resp: LinkAsNewVersionResponse) => void;
}

function RightPanel({
    spaceId,
    selectedFile,
    dismissPending,
    onDismiss,
    onLinked,
}: RightPanelProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const confirm = useConfirm();

    const [keyword, setKeyword] = useState("");
    const [submittedKeyword, setSubmittedKeyword] = useState("");
    const debouncedKeyword = useDebounce(keyword, 300);
    // Keep track of which file is currently showing so we can reset state on change
    const fileIdRef = useRef(selectedFile.knowledge_file_id);

    // Reset search whenever selected file changes
    useEffect(() => {
        if (fileIdRef.current !== selectedFile.knowledge_file_id) {
            fileIdRef.current = selectedFile.knowledge_file_id;
            setKeyword("");
            setSubmittedKeyword("");
        }
    }, [selectedFile.knowledge_file_id]);

    // Merge debounced + explicit submit: either path updates the active search term
    const activeKeyword = submittedKeyword || debouncedKeyword;

    // Fetch similarity recommendations for the selected file
    const { data: candidates = [], isLoading: candidatesLoading } = useQuery({
        queryKey: ["similar-candidates", selectedFile.knowledge_file_id],
        queryFn: () => getSimilarCandidatesApi(selectedFile.knowledge_file_id),
        enabled: selectedFile.knowledge_file_id > 0,
    });

    // Fetch search results when active keyword is at least 1 char
    const { data: searchResults = [], isLoading: searchLoading } = useQuery({
        queryKey: ["document-search", spaceId, activeKeyword],
        queryFn: () => searchDocumentsApi(spaceId, activeKeyword, selectedFile.knowledge_file_id),
        enabled: activeKeyword.length >= 1,
    });

    const linkMutation = useMutation({
        mutationFn: (target_document_id: number) =>
            linkAsNewVersionApi({
                knowledge_file_id: selectedFile.knowledge_file_id,
                target_document_id,
            }),
        onSuccess: (response) => {
            showToast({
                message: localize("com_knowledge.version.toast_link_success"),
                status: "success",
            });
            onLinked(response);
        },
        // The unified request interceptor already toasts api_errors.<code>
        // when skip403Redirect is set, so onError here can be a no-op.
        onError: () => undefined,
    });

    const handleLink = async (targetDoc: { document_id: number; title: string }) => {
        const ok = await confirm({
            title: localize("com_knowledge.version.confirm_link_title"),
            description: localize("com_knowledge.version.confirm_link_description", {
                name: selectedFile.file_name,
                target: targetDoc.title,
            }),
        });
        if (ok) {
            linkMutation.mutate(targetDoc.document_id);
        }
    };

    const isLinking = linkMutation.isPending;
    const hasSearched = activeKeyword.length >= 1;

    const handleSearchSubmit = () => {
        setSubmittedKeyword(keyword);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === "Enter") {
            handleSearchSubmit();
        }
    };

    return (
        <div className="flex flex-col gap-5 px-5 py-4 h-full">
            {/* ── Section 1: Current file ─────────────────────────────── */}
            <section className="rounded-[8px] border border-[#EBECF0] bg-[#FAFAFA] px-4 py-3 flex items-start justify-between shrink-0">
                <div className="flex-1 min-w-0 pr-4">
                    <p className="text-[12px] text-[#86909c] mb-1">
                        {localize("com_knowledge.version.section_current_file")}
                    </p>
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <p className="truncate text-[16px] font-medium text-[#1d2129] mb-1">
                                {selectedFile.file_name}
                            </p>
                        </TooltipTrigger>
                        <TooltipContent
                            noArrow
                            side="top"
                            className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-[12px] text-white"
                        >
                            {selectedFile.file_name}
                        </TooltipContent>
                    </Tooltip>
                    <p className="text-[12px] text-[#86909c]">
                        {selectedFile.file_code ? `${selectedFile.file_code} · ` : ""}当前主版本 V{selectedFile.current_primary_version_no ?? 1} · 上传人 {selectedFile.primary_uploader_name ?? "未知"}
                    </p>
                </div>
                <span className="shrink-0 rounded bg-[#FFF3E8] px-2 py-0.5 text-[12px] text-[#F76F44] font-medium mt-1">
                    {localize("com_knowledge.version.current_file_recommend_pill", {
                        count: selectedFile.candidate_count,
                    })}
                </span>
            </section>

            {/* ── Sections 2 & 3: Recommendations and Search ──────────── */}
            <div className="shrink-0 flex flex-col gap-5 rounded-[8px] border border-[#EBECF0] bg-[#FAFAFA] p-4">
                {/* ── Section 2: Recommendations ──────────────────────────── */}
                <section>
                    <h3 className="mb-0.5 text-[14px] font-medium text-[#1d2129]">
                        {localize("com_knowledge.version.section_recommendations")}
                    </h3>
                    <p className="mb-3 text-[12px] text-[#86909c]">
                        {localize("com_knowledge.version.section_recommendations_subtitle")}
                    </p>
                    {candidatesLoading ? (
                        <div className="flex h-16 items-center justify-center">
                            <Loader2 className="size-5 animate-spin text-[#86909c]" />
                        </div>
                    ) : candidates.length === 0 ? (
                        <p className="text-[14px] text-[#86909c]">
                            {localize("com_knowledge.version.no_recommendations")}
                        </p>
                    ) : (
                        <div className="flex flex-col gap-2 max-h-[220px] overflow-y-auto scrollbar-on-scroll">
                            {candidates.map((entry) => (
                                <RecommendationCard
                                    key={entry.target_document_id}
                                    entry={entry}
                                    disabled={isLinking || dismissPending}
                                    onLink={handleLink}
                                />
                            ))}
                        </div>
                    )}
                </section>

                {/* ── Section 3: Search existing documents ────────────────── */}
                <section>
                    <h3 className="mb-0.5 text-[14px] font-medium text-[#1d2129]">
                        {localize("com_knowledge.version.section_search")}
                    </h3>
                    <p className="mb-3 text-[12px] text-[#86909c]">
                        {localize("com_knowledge.version.section_search_subtitle")}
                    </p>
                    {/* Search input + button row */}
                    <div className="mb-3 flex gap-2">
                        <Input
                            type="text"
                            value={keyword}
                            onChange={(e) => setKeyword(e.target.value)}
                            onKeyDown={handleKeyDown}
                            placeholder={localize("com_knowledge.version.search_placeholder")}
                            className="h-8 flex-1 rounded-[6px] border-[#EBECF0] text-[12px] bg-white"
                        />
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={handleSearchSubmit}
                            className="h-8 rounded-[6px] px-4 text-[12px] text-[#4e5969] bg-white border-[#EBECF0]"
                        >
                            <Search className="mr-1.5 size-4" />
                            {localize("com_knowledge.version.search_button")}
                        </Button>
                    </div>

                    {/* Search results or placeholder */}
                    {!hasSearched ? (
                        // Centered placeholder hint when no keyword has been entered
                        <div className="flex h-16 items-center justify-center rounded-[6px] border border-dashed border-[#EBECF0] bg-white">
                            <p className="text-[14px] text-[#c9cdd4]">
                                {localize("com_knowledge.version.search_placeholder")}
                            </p>
                        </div>
                    ) : (
                        <div className="rounded-[6px] border border-[#EBECF0] bg-white">
                            {searchLoading ? (
                                <div className="flex h-16 items-center justify-center">
                                    <Loader2 className="size-5 animate-spin text-[#86909c]" />
                                </div>
                            ) : searchResults.length === 0 ? (
                                <p className="px-3 py-4 text-[14px] text-[#86909c]">
                                    {localize("com_knowledge.version.no_search_results")}
                                </p>
                            ) : (
                                <div className="max-h-[220px] overflow-y-auto scrollbar-on-scroll">
                                    {searchResults.map((entry) => (
                                        <SearchResultRow
                                            key={entry.document_id}
                                            entry={entry}
                                            disabled={isLinking || dismissPending}
                                            onLink={handleLink}
                                        />
                                    ))}
                                </div>
                            )}
                        </div>
                    )}
                </section>
            </div>

            {/* ── Section 4: Skip linking ─────────────────────────────── */}
            <section className="mt-auto shrink-0 rounded-[8px] border border-dashed border-[#EBECF0] bg-white px-4 py-3 flex items-center justify-between">
                <div>
                    <h3 className="mb-1 text-[14px] font-medium text-[#1d2129]">
                        {localize("com_knowledge.version.section_dismiss")}
                    </h3>
                    <p className="text-[12px] text-[#86909c]">
                        {localize("com_knowledge.version.section_dismiss_subtitle")}
                    </p>
                </div>
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={dismissPending || isLinking}
                    onClick={onDismiss}
                    className="h-8 shrink-0 rounded-[6px] px-4 text-[12px] text-[#4e5969]"
                >
                    <Check className="mr-1.5 size-4" />
                    {localize("com_knowledge.version.btn_dismiss")}
                </Button>
            </section>
        </div>
    );
}

// ─── Main component ────────────────────────────────────────────────────────────

export function SimilarDocumentDialog({
    open,
    onOpenChange,
    spaceId,
    restrictToFileIds,
    onProcessed,
}: SimilarDocumentDialogProps): JSX.Element | null {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    const [selectedFileId, setSelectedFileId] = useState<number | null>(null);

    // Fetch the list of pending similar files
    const { data: pending = [], isLoading, refetch: _refetch } = useQuery({
        queryKey: ["pending-similar", spaceId],
        queryFn: () => getPendingSimilarFilesApi(spaceId),
        enabled: open && spaceId > 0,
    });

    // Restrict the pending list to the caller-selected files (batch entry). When no
    // restriction is given, show every pending similar file in the space.
    const visiblePending = useMemo(() => {
        if (!restrictToFileIds || restrictToFileIds.length === 0) return pending;
        const allow = new Set(restrictToFileIds);
        return pending.filter((e) => allow.has(String(e.knowledge_file_id)));
    }, [pending, restrictToFileIds]);

    // Auto-select the first item whenever data loads or changes
    useEffect(() => {
        if (visiblePending.length > 0) {
            setSelectedFileId((prev) => {
                // Keep current selection if it still exists in the list
                if (prev !== null && visiblePending.some((e) => e.knowledge_file_id === prev)) {
                    return prev;
                }
                return visiblePending[0].knowledge_file_id;
            });
        } else {
            setSelectedFileId(null);
        }
    }, [visiblePending]);

    // Reset selection when dialog closes
    useEffect(() => {
        if (!open) {
            setSelectedFileId(null);
        }
    }, [open]);

    // Dismiss mutation — marks the file as "don't link"
    const dismissMutation = useMutation({
        mutationFn: (fileId: number) => dismissSimilarApi(fileId),
        onSuccess: () => {
            showToast({
                message: localize("com_knowledge.version.toast_dismiss_success"),
                status: "success",
            });
            queryClient.invalidateQueries({ queryKey: ["pending-similar", spaceId] });
            onProcessed?.();
            setSelectedFileId(null); // wait for refetch to auto-select the next one
        },
        onError: () => {
            showToast({
                message: localize("com_knowledge.version.toast_link_failure"),
                status: "error",
            });
        },
    });

    // Callback fired after a successful link
    const handleLinked = (_resp: LinkAsNewVersionResponse) => {
        queryClient.invalidateQueries({ queryKey: ["pending-similar", spaceId] });
        onProcessed?.();
        setSelectedFileId(null); // refetch will re-auto-select next pending
    };

    // Derive the currently selected entry
    const selectedFile = visiblePending.find((e) => e.knowledge_file_id === selectedFileId) ?? null;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className="flex max-w-[960px] min-h-[560px] max-h-[80vh] flex-col gap-0 rounded-xl border-none bg-white p-0 shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] outline-none overflow-hidden"
            >
                {/* ── Header ──────────────────────────────────────────────── */}
                <DialogHeader className="shrink-0 border-b border-[#e5e6eb] px-6 py-4 text-left">
                    <DialogTitle className="text-base font-semibold text-[#1d2129]">
                        {localize("com_knowledge.version.similar_dialog_title")}
                    </DialogTitle>
                </DialogHeader>

                {/* ── Body ────────────────────────────────────────────────── */}
                {isLoading ? (
                    // Loading state — simple centered spinner
                    <div className="flex flex-1 items-center justify-center py-16">
                        <Loader2 className="size-6 animate-spin text-[#86909c]" />
                    </div>
                ) : visiblePending.length === 0 ? (
                    // Empty state — all files processed
                    <div className="flex flex-1 items-center justify-center py-16 text-sm text-[#86909c]">
                        {localize("com_knowledge.version.similar_dialog_empty")}
                    </div>
                ) : (
                    // Two-column layout: left = file list (~30%), right = action panel
                    <div className="flex min-h-0 flex-1 overflow-hidden">
                        {/* Left column — pending file list (~30%) */}
                        <div className="flex w-[260px] shrink-0 flex-col border-r border-[#e5e6eb] bg-[#FAFAFA]">
                            <div className="px-5 py-4 text-[12px] text-[#86909c] border-b border-[#e5e6eb]">
                                {localize("com_knowledge.version.similar_dialog_subtitle", { count: visiblePending.length })}
                            </div>
                            {/* Scrollable file list */}
                            <div className="flex-1 overflow-y-auto scrollbar-on-scroll px-3 py-3">
                                {visiblePending.map((entry) => (
                                    <PendingFileRow
                                        key={entry.knowledge_file_id}
                                        entry={entry}
                                        isSelected={selectedFileId === entry.knowledge_file_id}
                                        onClick={() =>
                                            setSelectedFileId(entry.knowledge_file_id)
                                        }
                                    />
                                ))}
                            </div>
                        </div>

                        {/* Right column — 4-section action panel (~70%) */}
                        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                            {selectedFileId === null || selectedFile === null ? (
                                // No selection placeholder
                                <div className="flex flex-1 items-center justify-center text-sm text-[#86909c]">
                                    {localize("com_knowledge.version.similar_dialog_right_empty")}
                                </div>
                            ) : (
                                <div className="flex-1 overflow-y-auto scrollbar-on-scroll">
                                    <RightPanel
                                        key={selectedFile.knowledge_file_id}
                                        spaceId={spaceId}
                                        selectedFile={selectedFile}
                                        dismissPending={dismissMutation.isPending}
                                        onDismiss={() =>
                                            dismissMutation.mutate(selectedFileId)
                                        }
                                        onLinked={handleLinked}
                                    />
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* ── Footer ──────────────────────────────────────────────── */}
                <div className="shrink-0 border-t border-[#e5e6eb] px-6 py-3 flex justify-end">
                    <Button
                        type="button"
                        variant="outline"
                        className="h-8 rounded-[6px] px-4 font-normal"
                        onClick={() => onOpenChange(false)}
                    >
                        {localize("com_knowledge.version.btn_close")}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
