/**
 * F035: shared file-preview body — resolves the artifact source (text / image)
 * and renders it (markdown / plain text / image / "download to view" fallback).
 * Used by both the legacy drawer (FilePreviewPanel) and the inline WorkspacePanel
 * so the two surfaces render identical content.
 */
import { Colored } from 'bisheng-icons';
import { useEffect, useState } from 'react';
import { NotificationSeverity } from '~/common';
import Markdown from '~/components/Chat/Messages/Content/Markdown';
import { Button } from '~/components/ui';
import FileIcon from '~/components/ui/icon/File';
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

// Colored placeholder icons (bisheng-icons) for the "can't preview" fallback,
// by extension. Types without a colored variant (e.g. pdf) fall back to FileIcon.
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

// Module-level cache of resolved previews. Toggling fullscreen remounts a second
// WorkspacePanel instance, which would otherwise re-fetch and flash a spinner every
// time. Artifacts are immutable per version, so versionId+url is a safe key — a hit
// lets the new instance render instantly with no spinner and no network round-trip.
const previewCache = new Map<string, { text?: string; imageUrl?: string }>();
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

    useEffect(() => {
        setError(false);
        if (!file) {
            setText('');
            setImageUrl('');
            setLoading(false);
            return undefined;
        }
        const kind = getArtifactPreviewKind(file);
        if (kind === 'unsupported') {
            setText('');
            setImageUrl('');
            setLoading(false);
            return undefined;
        }

        const key = previewCacheKey(file, versionId);
        const hit = previewCache.get(key);
        if (hit) {
            // Already fetched — render immediately, no spinner, no refetch.
            setText(hit.text ?? '');
            setImageUrl(hit.imageUrl ?? '');
            setLoading(false);
            return undefined;
        }

        let cancelled = false;
        setText('');
        setImageUrl('');
        setLoading(true);
        (async () => {
            try {
                const url = await resolveArtifactUrl(file.file_url, versionId);
                if (cancelled) return;
                if (kind === 'image') {
                    previewCache.set(key, { imageUrl: url });
                    setImageUrl(url);
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

    return { loading, error, text, imageUrl };
}

interface PreviewBodyProps {
    file: ArtifactFile;
    versionId: string;
}

export function PreviewBody({ file, versionId }: PreviewBodyProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const { loading, error, text, imageUrl } = usePreviewSource(file, versionId);
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
        return (
            <div className="flex h-full flex-col items-center justify-center gap-2 p-6">
                {ColoredIcon ? (
                    <ColoredIcon className="h-20 w-20" />
                ) : (
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- FileIcon accepts more types than its union
                    <FileIcon type={ext as any} className="h-20 w-20" />
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
        // Match the task workbench loading (SopLoading): the linsi-load image inside
        // the rotating-border box, instead of the generic spinner.
        return (
            <div className="flex h-full items-center justify-center">
                <div className="lingsi-border-box">
                    <div
                        className="h-[102px] w-[194px] rounded-md bg-white bg-no-repeat"
                        style={{ backgroundImage: `url(${__APP_ENV__.BASE_URL}/assets/linsi-load.png)` }}
                    />
                </div>
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
