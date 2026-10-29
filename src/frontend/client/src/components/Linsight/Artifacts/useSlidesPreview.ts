/**
 * F111: PDF preview of a task-generated .ppt/.pptx.
 *
 * The backend converts the deck on first open and caches the PDF in object
 * storage. While another request holds the conversion it answers `converting`;
 * we poll every POLL_INTERVAL_MS and give up after POLL_TIMEOUT_MS so the panel
 * never spins forever — the next open usually hits the finished cache.
 */
import { useEffect, useState } from 'react';
import { getLinsightFilePreviewApi } from '~/api/chat/data-service';
import { getShareTokenFromPath } from '~/utils/shareToken';
import { type ArtifactFile, getArtifactPreviewKind } from './artifactUtils';

export const POLL_INTERVAL_MS = 2000;
export const POLL_TIMEOUT_MS = 90_000;

export type SlidesPreviewState = 'idle' | 'generating' | 'ready' | 'failed';

// Successes only: a failed conversion must be retried on the next open.
const readyCache = new Map<string, string>();
const cacheKey = (file: ArtifactFile, versionId: string) => `${versionId}::${file.file_url}`;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

/**
 * Poll the preview endpoint until it is ready, fails, or the deadline passes.
 * Returns the PDF URL (BASE_URL-prefixed, same as resolveArtifactUrl), or null on
 * failure / timeout / cancellation.
 */
export async function pollSlidesPreview(
    fileUrl: string,
    versionId: string,
    isCancelled: () => boolean,
    shareToken: string = getShareTokenFromPath(),
    now: () => number = Date.now,
): Promise<string | null> {
    const deadline = now() + POLL_TIMEOUT_MS;
    while (!isCancelled()) {
        const res = await getLinsightFilePreviewApi(fileUrl, versionId, shareToken);
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
    const isSlides = !!file && getArtifactPreviewKind(file) === 'slides';
    const cached = isSlides && file ? readyCache.get(cacheKey(file, versionId)) : undefined;
    const [state, setState] = useState<SlidesPreviewState>(cached ? 'ready' : isSlides ? 'generating' : 'idle');
    const [url, setUrl] = useState(cached ?? '');

    useEffect(() => {
        if (!file || getArtifactPreviewKind(file) !== 'slides') {
            setState('idle');
            setUrl('');
            return undefined;
        }
        const key = cacheKey(file, versionId);
        const hit = readyCache.get(key);
        if (hit) {
            setUrl(hit);
            setState('ready');
            return undefined;
        }
        let cancelled = false;
        setUrl('');
        setState('generating');
        pollSlidesPreview(file.file_url, versionId, () => cancelled)
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
    }, [file, versionId]);

    return { state, url };
}
