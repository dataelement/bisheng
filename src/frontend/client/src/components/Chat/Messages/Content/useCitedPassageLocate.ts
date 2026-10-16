/**
 * Land a source preview on the passage a citation points at.
 *
 * PDFs highlight through their bbox inside PdfViewer. docx / md / txt carry no
 * coordinates (ingestion turns them into markdown), so the cited chunk text is
 * matched against the rendered viewer DOM instead (citationLocate). Spreadsheets
 * have no passage to land on, and a match can fail — both report 'missed' so the
 * host shows the quoted text rather than silently opening the file at the top.
 * A failed match is only reported after the viewer stops rendering, so the
 * quote banner never flashes while the passage is still on its way.
 *
 * Shared by every citation preview: the task-mode source pane, the daily-chat
 * docked reference panel and the knowledge-space preview drawer.
 */
import { useEffect, useState, type RefObject } from 'react';
import { clearCitedHighlight, highlightCitedText } from './citationLocate';

export type CitedPassageLocateState = 'pending' | 'found' | 'missed' | 'native';

/** Viewers that highlight on their own (bbox) or render media — nothing to match. */
const NATIVE_LOCATE_TYPES = new Set(['pdf', 'mp3', 'wav', 'm4a', 'mp4', 'mov', 'webm', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']);
/** Tables have no passage to land on; show the quote straight away. */
const QUOTE_ONLY_TYPES = new Set(['xlsx', 'xls', 'csv']);
/**
 * A docx / md preview renders in several passes, so a miss on an early pass
 * often only means the cited passage has not been rendered yet. Report 'missed'
 * only once the viewer has stopped changing for this long; otherwise the quote
 * banner flashes up and disappears a moment later when the match lands.
 */
export const MISS_SETTLE_MS = 1000;

/**
 * @param rootRef element wrapping the rendered viewer
 * @param fileType viewer type once the file url resolved ('' while resolving)
 * @param chunks cited chunk texts; empty disables locating
 */
export function useCitedPassageLocate(
    rootRef: RefObject<HTMLElement | null>,
    fileType: string,
    chunks: string[],
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
            setLocate(chunks.length ? 'missed' : 'native');
            return undefined;
        }

        setLocate('pending');
        let timer = 0;
        let missTimer = 0;
        const attempt = () => {
            // Loading placeholders are short; wait for real content.
            if ((root.textContent || '').length < 40) return;
            if (highlightCitedText(root, chunks)) {
                window.clearTimeout(missTimer);
                setLocate('found');
                observer.disconnect();
                return;
            }
            // Not there yet: stay pending until the viewer settles (any later
            // render restarts this wait), and only then admit the miss.
            window.clearTimeout(missTimer);
            missTimer = window.setTimeout(() => setLocate('missed'), MISS_SETTLE_MS);
        };
        const observer = new MutationObserver(() => {
            window.clearTimeout(timer);
            window.clearTimeout(missTimer);
            timer = window.setTimeout(attempt, 200);
        });
        observer.observe(root, { childList: true, subtree: true, characterData: true });
        attempt();
        return () => {
            window.clearTimeout(timer);
            window.clearTimeout(missTimer);
            observer.disconnect();
        };
    }, [rootRef, chunks, fileType]);

    return locate;
}
