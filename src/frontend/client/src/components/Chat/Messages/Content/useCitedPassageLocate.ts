/**
 * Land a source preview on the passage a citation points at.
 *
 * PDFs highlight through their bbox inside PdfViewer. docx / md / txt carry no
 * coordinates (ingestion turns them into markdown), so the cited chunk text is
 * matched against the rendered viewer body instead (citationLocate). A missing
 * match leaves the file at its beginning without showing an error or quote.
 *
 * Shared by every citation preview: the task-mode source pane, the daily-chat
 * docked reference panel and the knowledge-space preview drawer.
 */
import { useEffect, useState, type RefObject } from 'react';
import { clearCitedHighlight, highlightCitedText } from './citationLocate';

export type CitedPassageLocateState = 'pending' | 'found' | 'missed' | 'native';

/** Viewers that highlight on their own (bbox) or render media — nothing to match. */
const NATIVE_LOCATE_TYPES = new Set(['pdf', 'mp3', 'wav', 'm4a', 'mp4', 'mov', 'webm', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']);
/** Tables have no passage to land on; retain the normal file preview. */
const QUOTE_ONLY_TYPES = new Set(['xlsx', 'xls', 'csv']);

/**
 * @param rootRef element wrapping the rendered viewer
 * @param fileType viewer type once the file url resolved ('' while resolving)
 * @param chunks cited chunk texts; empty disables locating
 */
export function useCitedPassageLocate(
    rootRef: RefObject<HTMLElement | null>,
    fileType: string,
    chunks: string[],
    documentKey = '',
): CitedPassageLocateState {
    const [locate, setLocate] = useState<CitedPassageLocateState>('pending');

    // Locate once the viewer has rendered. Stepping to another passage of the
    // same file keeps the DOM, so try immediately; a new file renders
    // asynchronously (fetch + mammoth / markdown), so watch for it.
    useEffect(() => {
        const root = rootRef.current;
        if (!root) return undefined;
        clearCitedHighlight(root);
        if (!fileType) {
            setLocate('pending');
            return undefined;
        }
        if (NATIVE_LOCATE_TYPES.has(fileType)) {
            setLocate('native');
            return undefined;
        }
        if (QUOTE_ONLY_TYPES.has(fileType) || !chunks.length) {
            const viewport = root.querySelector<HTMLElement>('[data-citation-scroll-container]');
            if (viewport) viewport.scrollTop = 0;
            setLocate(chunks.length ? 'missed' : 'native');
            return undefined;
        }

        setLocate('pending');
        let timer = 0;
        let locatedBody: HTMLElement | null = null;
        const attempt = () => {
            // Toolbar paragraphs (e.g. the zoom percentage) are not evidence
            // that the asynchronously loaded document body is available.
            const body = root.querySelector<HTMLElement>('[data-citation-document-body]');
            if (!body) return;
            if (locatedBody && locatedBody !== body) clearCitedHighlight(locatedBody);
            locatedBody = body;
            if (highlightCitedText(body, chunks)) {
                setLocate('found');
                observer.disconnect();
            } else {
                const viewport = root.querySelector<HTMLElement>('[data-citation-scroll-container]');
                if (viewport) viewport.scrollTop = 0;
                setLocate('missed');
            }
        };
        const observer = new MutationObserver(() => {
            window.clearTimeout(timer);
            timer = window.setTimeout(attempt, 200);
        });
        observer.observe(root, { childList: true, subtree: true, characterData: true });
        attempt();
        return () => {
            window.clearTimeout(timer);
            observer.disconnect();
            if (locatedBody) clearCitedHighlight(locatedBody);
            clearCitedHighlight(root);
        };
    }, [rootRef, chunks, fileType, documentKey]);

    return locate;
}
