import { directoryTitleClass } from "@bisheng/knowledge";
import { Button, Modal, ModalClose } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { lazy, Suspense, useEffect, useState } from "react";
import { useUnactivate } from "react-activation";
import { useLocalize } from "~/hooks";
import { cn } from "~/utils";
import { getClientEnvironment } from "~/utils/clientEnvironment";
import { KnowledgeSpaceBackControl } from "../KnowledgeSpaceBackControl";

const KnowledgeFileReader = lazy(() =>
    import("./FilePreviewPage").then(({ KnowledgeFileReader }) => ({ default: KnowledgeFileReader })),
);

export function getEmbeddedKnowledgeFileReader() {
    const { channel, capabilities } = getClientEnvironment();
    if (channel === "desktop") return "desktop";
    if (capabilities.hasHostChatHeader) return "mobile-app";
    return undefined;
}

interface KnowledgeFilePreviewTarget {
    spaceId: string;
    fileId: string;
    fileName: string;
    embedded: NonNullable<ReturnType<typeof getEmbeddedKnowledgeFileReader>>;
    aboveDialog: boolean;
    opener: HTMLElement | null;
}

export function useKnowledgeFilePreview(spaceId: string | undefined) {
    const [filePreview, setFilePreview] = useState<KnowledgeFilePreviewTarget | null>(null);
    useEffect(() => setFilePreview(null), [spaceId]);
    useUnactivate(() => setFilePreview(null));

    function openFilePreview(fileId: string, fileName: string, aboveDialog = false) {
        if (!spaceId) return;
        const embedded = getEmbeddedKnowledgeFileReader();
        if (embedded) {
            const active = document.activeElement;
            setFilePreview({
                spaceId,
                fileId,
                fileName,
                embedded,
                aboveDialog,
                opener: active instanceof HTMLElement && active !== document.body ? active : null,
            });
            return;
        }
        const ext = fileName.split(".").pop()?.toLowerCase() || "";
        const url = `${__APP_ENV__.BASE_URL}/knowledge/file/${fileId}?name=${encodeURIComponent(fileName)}&type=${encodeURIComponent(ext)}&spaceId=${encodeURIComponent(spaceId)}`;
        window.open(url, "_blank");
    }

    return {
        filePreview: filePreview?.spaceId === spaceId ? filePreview : null,
        openFilePreview,
        closeFilePreview: () => setFilePreview(null),
    };
}

interface KnowledgeFilePreviewOverlayProps {
    preview: KnowledgeFilePreviewTarget;
    onClose: () => void;
}

export function KnowledgeFilePreviewOverlay({ preview, onClose }: KnowledgeFilePreviewOverlayProps) {
    const localize = useLocalize();
    const [container, setContainer] = useState<HTMLDivElement | null>(null);
    const { aboveDialog, fileId, fileName, spaceId, embedded, opener } = preview;
    const isDesktop = embedded === "desktop";
    const backLabel = localize("com_ui_go_back");
    const title = (
        <span className={cn("flex min-w-0 items-center", isDesktop ? "gap-1 text-sm font-normal" : "gap-2")}>
            {isDesktop ? (
                <KnowledgeSpaceBackControl label={backLabel} onClick={onClose} />
            ) : (
                <ModalClose asChild>
                    <Button color="default" variant="text" size="medium">
                        <Outlined.ArrowLeft />
                        {backLabel}
                    </Button>
                </ModalClose>
            )}
            <span className={isDesktop ? directoryTitleClass : "truncate"}>{fileName}</span>
        </span>
    );
    return (
        <>
            {!aboveDialog && <div ref={setContainer} />}
            {(aboveDialog || container) && (
                <Modal
                    open
                    container={container}
                    size="fullscreen"
                    title={title}
                    closable={false}
                    maskClosable={false}
                    onOpenChange={(open) => { if (!open) onClose(); }}
                    onCloseAutoFocus={(event) => {
                        if (!opener?.isConnected) return;
                        event.preventDefault();
                        opener.focus({ preventScroll: true });
                    }}
                    className={cn(
                        !aboveDialog && "absolute",
                        isDesktop && "[&_[data-slot=file-preview-toolbar]]:py-2",
                        // A desktop body portal also covers the native titlebar.
                        aboveDialog && isDesktop && "pt-[max(48px,var(--dsh-chat-viewport-top,0px))]",
                    )}
                    headerClassName={isDesktop ? "h-8 items-start px-0" : undefined}
                    bodyClassName="m-0 overflow-hidden p-0"
                >
                    <Suspense fallback={
                        <div role="status" className="flex h-full items-center justify-center text-text-3">
                            {localize("com_knowledge.loading")}
                        </div>
                    }>
                        <KnowledgeFileReader fileId={fileId} spaceId={spaceId} fileName={fileName} embedded={embedded} />
                    </Suspense>
                </Modal>
            )}
        </>
    );
}
