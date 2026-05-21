import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { Button } from "~/components/ui/Button";
import { Tooltip, TooltipTrigger, TooltipContent } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import {
    getPendingSimilarFilesApi,
    dismissSimilarApi,
    type PendingSimilarFileEntry,
    type LinkAsNewVersionResponse,
} from "~/api/knowledge";
import { RelateDocumentPanel } from "./RelateDocumentPanel";

// ─── Props ─────────────────────────────────────────────────────────────────────

interface SimilarDocumentDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    spaceId: number;
    /** Called after a file is linked or dismissed so parent can refetch file list */
    onProcessed?: () => void;
}

// ─── File list row ─────────────────────────────────────────────────────────────

interface PendingFileRowProps {
    entry: PendingSimilarFileEntry;
    isSelected: boolean;
    onClick: () => void;
}

function PendingFileRow({ entry, isSelected, onClick }: PendingFileRowProps) {
    // Format upload_time: replace T separator and trim to minute precision
    const displayTime = entry.upload_time
        ? entry.upload_time.replace("T", " ").slice(0, 16)
        : "";

    return (
        <button
            type="button"
            onClick={onClick}
            className={[
                "w-full text-left px-3 py-2.5 transition-colors rounded-[6px]",
                "hover:bg-[#f2f3f5] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary",
                isSelected ? "bg-[#e8f3ff]" : "",
            ].join(" ")}
        >
            <Tooltip>
                <TooltipTrigger asChild>
                    <p
                        className={[
                            "truncate text-sm font-medium",
                            isSelected ? "text-[#165dff]" : "text-[#1d2129]",
                        ].join(" ")}
                    >
                        {entry.file_name}
                    </p>
                </TooltipTrigger>
                <TooltipContent
                    noArrow
                    side="right"
                    className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-xs text-white"
                >
                    {entry.file_name}
                </TooltipContent>
            </Tooltip>
            <div className="mt-0.5 flex items-center gap-2 text-xs text-[#86909c]">
                {displayTime && <span>{displayTime}</span>}
                {entry.file_encoding && <span>{entry.file_encoding}</span>}
            </div>
        </button>
    );
}

// ─── Main component ────────────────────────────────────────────────────────────

export function SimilarDocumentDialog({
    open,
    onOpenChange,
    spaceId,
    onProcessed,
}: SimilarDocumentDialogProps): JSX.Element | null {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();

    const [selectedFileId, setSelectedFileId] = useState<number | null>(null);

    // Fetch the list of pending similar files
    const { data: pending = [], isLoading, refetch } = useQuery({
        queryKey: ["pending-similar", spaceId],
        queryFn: () => getPendingSimilarFilesApi(spaceId),
        enabled: open && spaceId > 0,
    });

    // Auto-select the first item whenever data loads or changes
    useEffect(() => {
        if (pending.length > 0) {
            setSelectedFileId((prev) => {
                // Keep current selection if it still exists in the list
                if (prev !== null && pending.some((e) => e.file_id === prev)) {
                    return prev;
                }
                return pending[0].file_id;
            });
        } else {
            setSelectedFileId(null);
        }
    }, [pending]);

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

    // Callback fired by RelateDocumentPanel after a successful link
    const handleLinked = (_resp: LinkAsNewVersionResponse) => {
        queryClient.invalidateQueries({ queryKey: ["pending-similar", spaceId] });
        onProcessed?.();
        setSelectedFileId(null); // refetch will re-auto-select next pending
    };

    // Derive the currently selected entry
    const selectedFile = pending.find((e) => e.file_id === selectedFileId) ?? null;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                close={false}
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
                ) : pending.length === 0 ? (
                    // Empty state — all files processed
                    <div className="flex flex-1 items-center justify-center py-16 text-sm text-[#86909c]">
                        {localize("com_knowledge.version.similar_dialog_empty")}
                    </div>
                ) : (
                    // Two-column layout: left = file list, right = relate panel
                    <div className="flex min-h-0 flex-1 overflow-hidden">
                        {/* Left column — pending file list (~40%) */}
                        <div className="flex w-[38%] shrink-0 flex-col border-r border-[#e5e6eb]">
                            {/* Left column header */}
                            <div className="shrink-0 border-b border-[#e5e6eb] px-4 py-3">
                                <p className="text-sm font-medium text-[#1d2129]">
                                    {localize("com_knowledge.version.similar_dialog_left_header", {
                                        count: pending.length,
                                    })}
                                </p>
                            </div>
                            {/* Scrollable file list */}
                            <div className="flex-1 overflow-y-auto scrollbar-on-scroll p-2">
                                {pending.map((entry) => (
                                    <PendingFileRow
                                        key={entry.file_id}
                                        entry={entry}
                                        isSelected={selectedFileId === entry.file_id}
                                        onClick={() => setSelectedFileId(entry.file_id)}
                                    />
                                ))}
                            </div>
                        </div>

                        {/* Right column — relate panel (~60%) */}
                        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                            {selectedFileId === null || selectedFile === null ? (
                                // No selection placeholder
                                <div className="flex flex-1 items-center justify-center text-sm text-[#86909c]">
                                    {localize("com_knowledge.version.similar_dialog_right_empty")}
                                </div>
                            ) : (
                                <>
                                    {/* Right panel header: selected file name + Dismiss button */}
                                    <div className="shrink-0 border-b border-[#e5e6eb] px-5 py-3">
                                        <div className="flex items-center justify-between gap-3">
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <p className="min-w-0 truncate text-sm font-medium text-[#1d2129]">
                                                        {selectedFile.file_name}
                                                    </p>
                                                </TooltipTrigger>
                                                <TooltipContent
                                                    noArrow
                                                    side="bottom"
                                                    className="max-w-xs rounded-md bg-[#1D2129] px-2 py-1 text-xs text-white"
                                                >
                                                    {selectedFile.file_name}
                                                </TooltipContent>
                                            </Tooltip>
                                            <Button
                                                type="button"
                                                variant="outline"
                                                size="sm"
                                                disabled={dismissMutation.isPending}
                                                onClick={() => dismissMutation.mutate(selectedFileId)}
                                                className="h-7 shrink-0 rounded-[6px] px-3 text-xs"
                                            >
                                                {localize("com_knowledge.version.btn_dismiss")}
                                            </Button>
                                        </div>
                                    </div>

                                    {/* RelateDocumentPanel — reused from Task 4 */}
                                    <div className="flex-1 overflow-y-auto scrollbar-on-scroll px-5 py-4">
                                        <RelateDocumentPanel
                                            spaceId={spaceId}
                                            fileId={selectedFileId}
                                            fileName={selectedFile.file_name}
                                            onLinked={handleLinked}
                                        />
                                    </div>
                                </>
                            )}
                        </div>
                    </div>
                )}
            </DialogContent>
        </Dialog>
    );
}
