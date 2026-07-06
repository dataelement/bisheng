/**
 * KnowledgeFilePreviewPane — self-contained compact preview for a single
 * knowledge file. Given a (spaceId, fileId), it fetches the preview URL,
 * resolves it, and renders the correct viewer (FilePreview / RichKnowledgePreview)
 * in compact mode. Used to place two previews side by side (version compare).
 */
import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { getFilePreviewApi } from "~/api/knowledge";
import { useLocalize } from "~/hooks";
import FilePreview from "~/pages/knowledge/FilePreview";
import { RichKnowledgePreview } from "~/pages/knowledge/FilePreview/RichKnowledgePreview";
import { resolveFilePreview } from "~/pages/knowledge/FilePreview/resolvePreview";

interface KnowledgeFilePreviewPaneProps {
    spaceId: number;
    fileId: number;
    fileName: string;
}

export function KnowledgeFilePreviewPane({ spaceId, fileId, fileName }: KnowledgeFilePreviewPaneProps) {
    const localize = useLocalize();

    const { data, isLoading, isError } = useQuery({
        queryKey: ["file-preview", spaceId, fileId],
        queryFn: () => getFilePreviewApi(String(spaceId), String(fileId)),
        enabled: spaceId > 0 && fileId > 0,
    });

    if (isLoading) {
        return (
            <div className="flex h-full items-center justify-center">
                <Loader2 className="size-6 animate-spin text-[#86909c]" />
            </div>
        );
    }

    if (isError || !data) {
        return (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm text-[#86909c]">
                {localize("com_knowledge.version.preview_load_failed")}
            </div>
        );
    }

    const resolved = resolveFilePreview(data);

    if (resolved.conversionFailed || !resolved.fileUrl) {
        return (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm text-[#86909c]">
                {localize("com_knowledge.version.preview_unavailable")}
            </div>
        );
    }

    return resolved.isRich ? (
        <RichKnowledgePreview
            fileName={fileName}
            preview={resolved.previewData}
            compactMode
            allowDownload={false}
        />
    ) : (
        <FilePreview
            fileName={fileName}
            fileType={resolved.fileType}
            fileUrl={resolved.fileUrl}
            compactMode
            allowDownload={false}
        />
    );
}
