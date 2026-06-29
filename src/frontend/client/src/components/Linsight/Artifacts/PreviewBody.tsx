/**
 * F035: shared file-preview body — resolves the artifact source (text / image)
 * and renders it (markdown / plain text / image / "download to view" fallback).
 * Used by both the legacy drawer (FilePreviewPanel) and the inline WorkspacePanel
 * so the two surfaces render identical content.
 */
import { Colored, Outlined } from 'bisheng-icons';
import { useEffect, useState } from 'react';
import { NotificationSeverity } from '~/common';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import FilePreview from '~/pages/knowledge/FilePreview';
import { Button } from '~/components/ui';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { useLocalize } from '~/hooks';
import '~/markdown.css';
import { useToastContext } from '~/Providers';
import {
    type ArtifactFile,
    downloadArtifactFile,
    getArtifactPreviewKind,
    getFileExtension,
    resolveArtifactUrl,
} from './artifactUtils';

// Placeholder icons (bisheng-icons) for the "can't preview" fallback, by extension.
// Prefer the Colored variant; types without one (pdf / image / unknown) fall back
// to a 20px Outlined icon (rendered inside an invisible 80×80 box so the footprint
// matches the colored icons).
const COLORED_FILE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
    doc: Colored.FileDoc,
    docx: Colored.FileDoc,
    xls: Colored.FileXls,
    xlsx: Colored.FileXls,
    ppt: Colored.FilePptx,
    pptx: Colored.FilePptx,
    csv: Colored.FileCsv,
    md: Colored.FileMd,
    txt: Colored.FileTxt,
};
const OUTLINED_FILE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
    pdf: Outlined.FilePdf,
    png: Outlined.FileImage,
    jpg: Outlined.FileImage,
    jpeg: Outlined.FileImage,
    gif: Outlined.FileImage,
    webp: Outlined.FileImage,
    bmp: Outlined.FileImage,
};

// Module-level cache of resolved previews. Toggling fullscreen remounts a second
// WorkspacePanel instance, which would otherwise re-fetch and flash a spinner every
// time. Artifacts are immutable per version, so versionId+url is a safe key — a hit
// lets the new instance render instantly with no spinner and no network round-trip.
const previewCache = new Map<string, { text?: string; imageUrl?: string; resolvedUrl?: string }>();
const previewCacheKey = (file: ArtifactFile, versionId: string) => `${versionId}::${file.file_url}`;

/** Resolve + load the preview source (text content or same-origin image url). */
export function usePreviewSource(file: ArtifactFile | null, versionId: string) {
    const cached = file ? previewCache.get(previewCacheKey(file, versionId)) : undefined;
    // Seed from cache so the first paint already shows content; only show the spinner
    // when there's a renderable file we haven't fetched yet.
    const [loading, setLoading] = useState(
        !!file && !cached && getArtifactPreviewKind(file) !== 'unsupported',
    );
    const [error, setError] = useState(false);
    const [text, setText] = useState(cached?.text ?? '');
    const [imageUrl, setImageUrl] = useState(cached?.imageUrl ?? '');
    // For 'document' kind we only resolve the share url and hand it to FilePreview,
    // which fetches/parses the bytes itself (pdfjs / mammoth / xlsx).
    const [resolvedUrl, setResolvedUrl] = useState(cached?.resolvedUrl ?? '');

    useEffect(() => {
        setError(false);
        if (!file) {
            setText('');
            setImageUrl('');
            setResolvedUrl('');
            setLoading(false);
            return undefined;
        }
        const kind = getArtifactPreviewKind(file);
        if (kind === 'unsupported') {
            setText('');
            setImageUrl('');
            setResolvedUrl('');
            setLoading(false);
            return undefined;
        }

        const key = previewCacheKey(file, versionId);
        const hit = previewCache.get(key);
        if (hit) {
            // Already fetched — render immediately, no spinner, no refetch.
            setText(hit.text ?? '');
            setImageUrl(hit.imageUrl ?? '');
            setResolvedUrl(hit.resolvedUrl ?? '');
            setLoading(false);
            return undefined;
        }

        let cancelled = false;
        setText('');
        setImageUrl('');
        setResolvedUrl('');
        setLoading(true);
        (async () => {
            try {
                const url = await resolveArtifactUrl(file.file_url, versionId);
                if (cancelled) return;
                if (kind === 'image') {
                    previewCache.set(key, { imageUrl: url });
                    setImageUrl(url);
                } else if (kind === 'document') {
                    // Resolve only — FilePreview's viewers fetch the bytes themselves.
                    previewCache.set(key, { resolvedUrl: url });
                    setResolvedUrl(url);
                } else {
                    const response = await fetch(url);
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const content = await response.text();
                    if (cancelled) return;
                    previewCache.set(key, { text: content });
                    setText(content);
                }
            } catch (e) {
                console.error('artifact preview failed:', e);
                if (!cancelled) setError(true);
            } finally {
                if (!cancelled) setLoading(false);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [file, versionId]);

    return { loading, error, text, imageUrl, resolvedUrl };
}

interface PreviewBodyProps {
    file: ArtifactFile;
    versionId: string;
}

export function PreviewBody({ file, versionId }: PreviewBodyProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const { loading, error, text, imageUrl, resolvedUrl } = usePreviewSource(file, versionId);
    const kind = getArtifactPreviewKind(file);

    const handleDownloadToView = async () => {
        try {
            await downloadArtifactFile(file, versionId);
        } catch (e) {
            console.error('artifact download failed:', e);
            showToast?.({ message: localize('com_linsight_download_failed'), severity: NotificationSeverity.ERROR });
        }
    };

    if (kind === 'unsupported' || error) {
        // not inline-renderable (docx / pdf / xlsx …) or load failure → download hint
        const ext = (getFileExtension(file.file_name) || '').toLowerCase();
        const ColoredIcon = COLORED_FILE_ICONS[ext];
        const OutlinedIcon = OUTLINED_FILE_ICONS[ext] ?? Outlined.File;
        return (
            <div className="flex h-full flex-col items-center justify-center gap-2 p-6">
                {ColoredIcon ? (
                    <ColoredIcon className="h-20 w-20" />
                ) : (
                    // No colored variant: 20px outlined icon centered in an invisible
                    // 80×80 box so the footprint matches the colored icons above.
                    <div className="flex h-20 w-20 items-center justify-center">
                        <OutlinedIcon className="size-5" />
                    </div>
                )}
                <div className="max-w-[80%] truncate text-base font-medium text-gray-900">{file.file_name}</div>
                <div className="mb-2 text-sm text-gray-500">
                    {error ? localize('com_linsight_preview_load_failed') : localize('com_linsight_preview_unsupported')}
                </div>
                <Button variant="outline" size="sm" onClick={handleDownloadToView} className="h-8 rounded-md px-4">
                    {localize('com_linsight_download_to_view')}
                </Button>
            </div>
        );
    }
    if (loading) {
        return (
            <div className="flex h-full flex-1 items-center justify-center">
                <LoadingIcon className="size-20 text-primary" />
            </div>
        );
    }
    if (kind === 'image') {
        return (
            <div className="flex h-full items-center justify-center p-4">
                <img className="max-h-full max-w-full object-contain" src={imageUrl} alt={file.file_name} />
            </div>
        );
    }
    if (kind === 'document') {
        // docx / pdf / xls / xlsx / csv → reuse the shared knowledge-space viewer.
        // compactMode = viewer only (no top bar / sidebar / zoom): Linsight's own
        // toolbar (back / download / fullscreen / close) provides the chrome.
        return (
            <FilePreview
                fileName={file.file_name}
                fileType={getFileExtension(file.file_name)}
                fileUrl={resolvedUrl}
                compactMode
            />
        );
    }
    if (kind === 'markdown') {
        return (
            <div className="bs-mkdown p-8">
                <Markdown content={text} isLatestMessage={true} webContent={false} />
            </div>
        );
    }
    // plain text
    return <pre className="whitespace-pre-wrap break-words p-6 text-sm text-gray-800">{text}</pre>;
}
