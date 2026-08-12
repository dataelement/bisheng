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

export function FileChangePreviewPage() {
    const localize = useLocalize();
    const { requestId } = useParams<{ requestId: string }>();
    const [searchParams] = useSearchParams();
    const fileName = searchParams.get("name") || localize("com_knowledge.unknown_file");
    const spaceId = searchParams.get("spaceId") || "";
    const fileType = useMemo(() => getFileType(fileName), [fileName]);
    const [fileUrl, setFileUrl] = useState("");
    const [loading, setLoading] = useState(true);
    const [failed, setFailed] = useState(false);

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
            <div className="flex h-[var(--bs-vh,100vh)] items-center justify-center bg-background text-text-3">
                {localize("com_knowledge.loading")}
            </div>
        );
    }

    if (failed || !fileUrl) {
        return (
            <div className="flex h-[var(--bs-vh,100vh)] items-center justify-center bg-background text-text-3">
                {localize("com_knowledge.file_change_preview_failed")}
            </div>
        );
    }

    return (
        <div className="h-[var(--bs-vh,100vh)] overflow-hidden bg-background">
            <FilePreview
                fileName={fileName}
                fileType={fileType}
                fileUrl={fileUrl}
            />
        </div>
    );
}
