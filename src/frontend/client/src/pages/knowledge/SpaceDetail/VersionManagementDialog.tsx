import { X } from "lucide-react";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
} from "~/components/ui";
import { Button } from "~/components/ui/Button";
import { useLocalize } from "~/hooks";
import { type KnowledgeFile, type LinkAsNewVersionResponse } from "~/api/knowledge";
import { RelateDocumentPanel } from "./RelateDocumentPanel";

// ─── Props ─────────────────────────────────────────────────────────────────────

interface VersionManagementDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    spaceId: number;
    file: KnowledgeFile | null;
    onLinked?: () => void;
}

// ─── Component ─────────────────────────────────────────────────────────────────

export function VersionManagementDialog({
    open,
    onOpenChange,
    spaceId,
    file,
    onLinked,
}: VersionManagementDialogProps): JSX.Element | null {
    const localize = useLocalize();

    if (!open || !file) {
        return null;
    }

    const handleLinked = (_response: LinkAsNewVersionResponse) => {
        onLinked?.();
        onOpenChange(false);
    };

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent
                className="flex w-full max-w-[720px] max-h-[85vh] flex-col gap-0 rounded-xl border-none bg-white p-0 shadow-[0px_5px_22px_0px_rgba(61,68,110,0.2)] outline-none [&>button]:hidden"
            >
                <DialogHeader className="relative shrink-0 border-b border-[#EBECF0] px-6 py-4 text-left">
                    <DialogTitle className="text-[16px] font-semibold text-[#1d2129]">
                        {localize("com_knowledge.version.dialog_title")}
                    </DialogTitle>
                    <button
                        type="button"
                        onClick={() => onOpenChange(false)}
                        className="absolute right-4 top-4 inline-flex size-8 items-center justify-center rounded-md text-[#4E5969] transition-colors hover:bg-[#F2F3F5]"
                        aria-label={localize("com_knowledge.close") || "Close"}
                    >
                        <X className="size-4" />
                    </button>
                </DialogHeader>

                <div className="flex-1 overflow-y-auto px-6 py-5">
                    <RelateDocumentPanel
                        spaceId={spaceId}
                        fileId={typeof file.id === "string" ? parseInt(file.id, 10) : file.id}
                        file={file}
                        onLinked={handleLinked}
                    />
                </div>

                <div className="flex shrink-0 items-center justify-end border-t border-[#EBECF0] px-6 py-3">
                    <Button
                        type="button"
                        variant="outline"
                        className="h-8 rounded-[6px] px-4 font-normal"
                        onClick={() => onOpenChange(false)}
                    >
                        {localize("com_knowledge.cancel")}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
