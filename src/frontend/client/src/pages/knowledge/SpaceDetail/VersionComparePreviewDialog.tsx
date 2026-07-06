/**
 * VersionComparePreviewDialog — side-by-side preview used from the similar-document
 * dialog's "查看" action. Left pane shows the current pending file, right pane shows
 * the candidate / associated file. Each pane is an independent FilePreview instance
 * (the preview component itself does not support a split view).
 */
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui/Dialog";
import { Tooltip, TooltipTrigger, TooltipContent } from "~/components/ui/Tooltip2";
import { useLocalize } from "~/hooks";
import { KnowledgeFilePreviewPane } from "./KnowledgeFilePreviewPane";

interface ComparePreviewSide {
    fileId: number;
    fileName: string;
}

interface VersionComparePreviewDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    spaceId: number;
    left: ComparePreviewSide | null;
    right: ComparePreviewSide | null;
}

/** One column: a label + filename header over a bordered preview area. */
function ComparePane({
    spaceId,
    side,
    label,
}: {
    spaceId: number;
    side: ComparePreviewSide;
    label: string;
}) {
    return (
        <div className="flex min-w-0 flex-1 flex-col">
            <div className="shrink-0 border-b border-[#e5e6eb] px-4 py-2">
                <p className="text-[12px] text-[#86909c]">{label}</p>
                <Tooltip>
                    <TooltipTrigger asChild>
                        <p className="truncate text-[14px] font-medium text-[#1d2129]">{side.fileName}</p>
                    </TooltipTrigger>
                    <TooltipContent
                        noArrow
                        side="bottom"
                        className="max-w-md rounded-md bg-[#1D2129] px-2 py-1 text-[12px] text-white"
                    >
                        {side.fileName}
                    </TooltipContent>
                </Tooltip>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden bg-[#FAFAFA]">
                <KnowledgeFilePreviewPane spaceId={spaceId} fileId={side.fileId} fileName={side.fileName} />
            </div>
        </div>
    );
}

export function VersionComparePreviewDialog({
    open,
    onOpenChange,
    spaceId,
    left,
    right,
}: VersionComparePreviewDialogProps): JSX.Element {
    const localize = useLocalize();

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="flex h-[85vh] w-[92vw] max-w-[1200px] flex-col gap-0 rounded-xl border-none bg-white p-0 shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] outline-none overflow-hidden">
                <DialogHeader className="shrink-0 border-b border-[#e5e6eb] px-6 py-4 text-left">
                    <DialogTitle className="text-base font-semibold text-[#1d2129]">
                        {localize("com_knowledge.version.compare_preview_title")}
                    </DialogTitle>
                </DialogHeader>
                <div className="flex min-h-0 flex-1 overflow-hidden">
                    {left && (
                        <ComparePane
                            spaceId={spaceId}
                            side={left}
                            label={localize("com_knowledge.version.compare_current_file")}
                        />
                    )}
                    <div className="w-px shrink-0 bg-[#e5e6eb]" />
                    {right && (
                        <ComparePane
                            spaceId={spaceId}
                            side={right}
                            label={localize("com_knowledge.version.compare_associated_file")}
                        />
                    )}
                </div>
            </DialogContent>
        </Dialog>
    );
}
