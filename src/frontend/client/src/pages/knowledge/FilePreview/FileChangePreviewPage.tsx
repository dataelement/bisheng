import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { getFileChangePreviewApi } from "~/api/knowledge";
import { useLocalize } from "~/hooks";

import FilePreview from "./index";
import { resolveKnowledgePreviewUrl } from "./previewUrlUtils";

function getFileType(fileName: string): string {
    const dotIndex = fileName.lastIndexOf(".");
    return dotIndex >= 0 && dotIndex < fileName.length - 1
        ? fileName.slice(dotIndex + 1).toLowerCase()
        : "";
}

export interface FileChangePreviewPageProps {
    /** Embedded mode: approval request id from props instead of the route param. */
    requestId?: string;
    /** Embedded mode: display name instead of the `name` query param. */
    fileName?: string;
    /** Embedded mode: space id instead of the `spaceId` query param. */
    spaceId?: string;
    /** Fill the parent instead of the viewport (side-drawer preview). */
    embedded?: boolean;
    /** Extra buttons rendered in the TopBar action slot (e.g. the drawer's close). */
    extraActions?: React.ReactNode;
}

/**
 * Preview of an upload still going through approval. Route-level page, and also
 * the body of `FilePreviewDrawer` when `embedded` is set.
 */
export function FileChangePreviewPage({
    requestId: requestIdProp,
    fileName: fileNameProp,
    spaceId: spaceIdProp,
    embedded = false,
    extraActions,
}: FileChangePreviewPageProps) {
    const localize = useLocalize();
    const { requestId: routeRequestId } = useParams<{ requestId: string }>();
    const [searchParams] = useSearchParams();
    const requestId = requestIdProp || routeRequestId;
    const fileName = fileNameProp || searchParams.get("name") || localize("com_knowledge.unknown_file");
    const spaceId = spaceIdProp || searchParams.get("spaceId") || "";
    const fileType = useMemo(() => getFileType(fileName), [fileName]);
    const [fileUrl, setFileUrl] = useState("");
    const [loading, setLoading] = useState(true);
    const [failed, setFailed] = useState(false);
    // Embedded in a drawer, the preview fills its container; standalone it owns the viewport.
    const rootHeightClass = embedded ? "h-full" : "h-[var(--bs-vh,100vh)]";

    useEffect(() => {
        const normalizedRequestId = Number(requestId);
        if (!spaceId || !Number.isInteger(normalizedRequestId) || normalizedRequestId <= 0) {
            setLoading(false);
            setFailed(true);
            return;
        }

        let cancelled = false;
        setLoading(true);
        setFailed(false);
        getFileChangePreviewApi(spaceId, normalizedRequestId)
            .then((result) => {
                if (cancelled) return;
                const previewUrl = result.previewUrl || result.originalUrl || "";
                setFileUrl(resolveKnowledgePreviewUrl(previewUrl));
                setFailed(!previewUrl);
            })
            .catch((error) => {
                console.error("Failed to load file-change preview:", error);
                if (!cancelled) setFailed(true);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });

        return () => {
            cancelled = true;
        };
    }, [requestId, spaceId]);

    if (loading) {
        return (
            <div className={`flex ${rootHeightClass} items-center justify-center bg-background text-text-3`}>
                {localize("com_knowledge.loading")}
            </div>
        );
    }

    if (failed || !fileUrl) {
        return (
            <div className={`flex ${rootHeightClass} items-center justify-center bg-background text-text-3`}>
                {localize("com_knowledge.file_change_preview_failed")}
            </div>
        );
    }

    return (
        <div className={`${rootHeightClass} overflow-hidden bg-background`}>
            <FilePreview
                fileName={fileName}
                fileType={fileType}
                fileUrl={fileUrl}
                trailingActions={extraActions}
            />
        </div>
    );
}
