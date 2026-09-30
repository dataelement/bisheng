/**
 * Land a source preview on the passage a citation points at.
 *
 * PDFs highlight through their bbox inside PdfViewer. docx / md / txt carry no
 * coordinates (ingestion turns them into markdown), so the cited chunk text is
 * matched against the rendered viewer DOM instead (citationLocate). Spreadsheets
 * have no passage to land on, and a match can fail — both report 'missed' so the
 * host shows the quoted text rather than silently opening the file at the top.
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
        const attempt = () => {
            // Loading placeholders are short; wait for real content.
            if ((root.textContent || '').length < 40) return;
            if (highlightCitedText(root, chunks)) {
                setLocate('found');
                observer.disconnect();
            } else {
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
        };
    }, [rootRef, chunks, fileType]);

    return locate;
}
