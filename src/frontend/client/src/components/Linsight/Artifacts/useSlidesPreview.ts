/**
 * F111: PDF preview of a task-generated .ppt/.pptx.
 *
 * The backend converts the deck on first open and caches the PDF in object
 * storage. While another request holds the conversion it answers `converting`;
 * we poll every POLL_INTERVAL_MS and give up after POLL_TIMEOUT_MS so the panel
 * never spins forever — the next open usually hits the finished cache.
 *
 * A deck of a deep-research turn converts through the task-result endpoint
 * (it needs the turn's version id). A deck a direct answer generated has no
 * version: it converts through the conversation-attachment endpoint, keyed by
 * conversation and file id. A deck with neither cannot be previewed.
 */
import { useEffect, useState } from 'react';
import { getConversationSlidesPreviewApi, getLinsightFilePreviewApi } from '~/api/chat/data-service';
import { getShareTokenFromPath } from '~/utils/shareToken';
import { type ArtifactFile, artifactVersionId, getArtifactPreviewKind } from './artifactUtils';

export const POLL_INTERVAL_MS = 2000;
export const POLL_TIMEOUT_MS = 90_000;

export type SlidesPreviewState = 'idle' | 'generating' | 'ready' | 'failed';

// Successes only: a failed conversion must be retried on the next open.
const readyCache = new Map<string, string>();
/** Where a deck's preview is converted: its task turn, or the conversation that keeps it. */
export type SlidesPreviewSource =
    | { kind: 'task'; fileUrl: string; versionId: string }
    | { kind: 'conversation'; conversationId: string; fileId: string };

export function slidesPreviewSource(file: ArtifactFile, versionId: string): SlidesPreviewSource | null {
    const vid = artifactVersionId(file, versionId);
    if (vid) return { kind: 'task', fileUrl: file.file_url, versionId: vid };
    if (file.attachment) {
        return { kind: 'conversation', conversationId: file.attachment.conversationId, fileId: file.attachment.fileId };
    }
    return null;
}

const sourceKey = (source: SlidesPreviewSource) =>
    source.kind === 'task'
        ? `task::${source.versionId}::${source.fileUrl}`
        : `conversation::${source.conversationId}::${source.fileId}`;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Poll the preview endpoint until it is ready, fails, or the deadline passes.
 * Returns the PDF URL (BASE_URL-prefixed, same as resolveArtifactUrl), or null on
 * failure / timeout / cancellation.
 */
export async function pollSlidesPreview(
    source: SlidesPreviewSource,
    isCancelled: () => boolean,
    shareToken: string = getShareTokenFromPath(),
    now: () => number = Date.now,
): Promise<string | null> {
    const deadline = now() + POLL_TIMEOUT_MS;
    while (!isCancelled()) {
        const res =
            source.kind === 'task'
                ? await getLinsightFilePreviewApi(source.fileUrl, source.versionId, shareToken)
                : await getConversationSlidesPreviewApi(source.conversationId, source.fileId, shareToken);
        const result = res?.data;
        if (result?.status === 'ready' && result.file_path) {
            return `${__APP_ENV__.BASE_URL}${result.file_path}`;
        }
        if (result?.status !== 'converting' || now() + POLL_INTERVAL_MS > deadline) return null;
        await sleep(POLL_INTERVAL_MS);
    }
    return null;
}

export function useSlidesPreview(file: ArtifactFile | null, versionId: string) {
    const source = file && getArtifactPreviewKind(file) === 'slides' ? slidesPreviewSource(file, versionId) : null;
    const isSlides = !!file && getArtifactPreviewKind(file) === 'slides';
    const key = source ? sourceKey(source) : '';
    const cached = key ? readyCache.get(key) : undefined;
    const [state, setState] = useState<SlidesPreviewState>(
        cached ? 'ready' : !isSlides ? 'idle' : source ? 'generating' : 'failed',
    );
    const [url, setUrl] = useState(cached ?? '');

    useEffect(() => {
        if (!isSlides) {
            setState('idle');
            setUrl('');
            return undefined;
        }
        setUrl('');
        if (!source) {
            // Neither a task turn nor a kept conversation file: nothing can convert it.
            setState('failed');
            return undefined;
        }
        const hit = readyCache.get(key);
        if (hit) {
            setUrl(hit);
            setState('ready');
            return undefined;
        }
        let cancelled = false;
        setState('generating');
        pollSlidesPreview(source, () => cancelled)
            .then((pdfUrl) => {
                if (cancelled) return;
                if (pdfUrl) {
                    readyCache.set(key, pdfUrl);
                    setUrl(pdfUrl);
                    setState('ready');
                } else {
                    setState('failed');
                }
            })
            .catch((e) => {
                console.error('slide preview failed:', e);
                if (!cancelled) setState('failed');
            });
        return () => {
            cancelled = true;
        };
        // `key` identifies the source; the source object itself is rebuilt every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [isSlides, key]);

    return { state, url };
}
