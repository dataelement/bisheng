/**
 * FilePreviewDrawer — side-drawer wrapper around the file preview pages.
 *
 * Desktop knowledge-space file clicks open the preview here instead of a new
 * browser tab, so the file list stays on screen behind the drawer. The body is
 * FilePreviewPage — or FileChangePreviewPage for an upload still awaiting
 * approval — in `embedded` mode, i.e. the same fetching, viewers, permissions
 * and AI dock as the standalone routes, which still serve direct links and
 * mobile taps.
 */
import { useEffect } from "react";
import { Outlined } from "bisheng-icons";
import { Button } from "~/components/ui/Button";
import { Sheet, SheetContent, SheetTitle } from "~/components/ui/Sheet";
import { useLocalize } from "~/hooks";
import { FileChangePreviewPage } from "./FileChangePreviewPage";
import FilePreviewPage from "./FilePreviewPage";

interface FilePreviewDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    /** Knowledge space id. */
    spaceId: string;
    /** Regular knowledge file being previewed. */
    fileId: string | null;
    /** Upload still awaiting approval — previewed by approval request id instead. */
    changeRequestId?: string | null;
    fileName: string;
}

export function FilePreviewDrawer({
    open,
    onOpenChange,
    spaceId,
    fileId,
    changeRequestId = null,
    fileName,
}: FilePreviewDrawerProps) {
    const localize = useLocalize();

    // FilePreview drives document.title (it was built for a full-page route).
    // In a drawer the page never changed, so put the title back on close.
    useEffect(() => {
        if (!open) return;
        const previousTitle = document.title;
        return () => {
            document.title = previousTitle;
        };
    }, [open]);

    // Close sits in the TopBar action slot, right of the More menu.
    const closeAction = (
        <Button
            variant="outline"
            className="h-8 w-8 p-2"
            aria-label={localize("com_knowledge.close")}
            onClick={() => onOpenChange(false)}
        >
            <Outlined.Close className="size-4 text-[#4e5969]" />
        </Button>
    );

    return (
        <Sheet open={open && !!(fileId || changeRequestId)} onOpenChange={onOpenChange}>
            <SheetContent
                side="right"
                hideClose
                className="flex h-full min-h-0 w-[1000px] max-w-[92vw] flex-col gap-0 overflow-hidden p-0 sm:max-w-[92vw]"
            >
                <SheetTitle className="sr-only">{fileName}</SheetTitle>

                {changeRequestId ? (
                    <FileChangePreviewPage
                        key={`change-${changeRequestId}`}
                        embedded
                        requestId={changeRequestId}
                        fileName={fileName}
                        spaceId={spaceId}
                        extraActions={closeAction}
                    />
                ) : fileId ? (
                    <FilePreviewPage
                        key={fileId}
                        embedded
                        fileId={fileId}
                        fileName={fileName}
                        spaceId={spaceId}
                        extraActions={closeAction}
                    />
                ) : null}
            </SheetContent>
        </Sheet>
    );
}
