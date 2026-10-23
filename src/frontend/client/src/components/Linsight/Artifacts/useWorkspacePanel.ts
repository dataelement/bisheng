/**
 * F035: state for the INLINE workspace panel embedded on the right of the
 * chat-embedded task mode (ChatView). Unlike the legacy drawer
 * (useArtifactsPanel), the panel stays mounted while switching between the
 * file list and the in-place file preview, and carries a `fullscreen` flag that
 * expands the preview to fill the whole chat `main` (the task-mode chat column
 * is hidden, not the browser).
 *
 *  - open === false           → panel hidden, header shows the entry button
 *  - open && !previewFile      → file-list view (fig. workspace)
 *  - open && previewFile       → in-place preview view (fig. preview)
 *  - … && sourcePreview        → F071 compare view: the report beside the cited
 *                                source file (the chat column gives up its width)
 */
import { useCallback, useEffect, useState } from 'react';
import type { CitationDocumentPreviewState } from '~/components/Chat/Messages/Content/CitationDocumentPreviewDrawer';

/** F071: a cited source plus which report badge (DOM-order position) opened it.
 *  Kept here, not in the panel, so the docked / fullscreen / narrow instances
 *  all agree on the citation being checked. */
export type SourcePreview = CitationDocumentPreviewState & { badgeIndex?: number };
import { isHtmlArtifact, openHtmlArtifactViewer, type ArtifactFile } from './artifactUtils';

export function useWorkspacePanel(versionId: string) {
    const [open, setOpen] = useState(false);
    const [previewFile, setPreviewFile] = useState<ArtifactFile | null>(null);
    const [fullscreen, setFullscreen] = useState(false);
    // F071: the cited source shown beside the report. It belongs to the report
    // being read, so every path that leaves that report also drops it.
    const [sourcePreview, setSourcePreview] = useState<SourcePreview | null>(null);

    // The panel is bound to ChatView's latest task turn (versionId). ChatView is
    // KeepAlive-cached, so switching conversations / new task / new chat never
    // unmounts this hook — it only changes versionId. Reset the panel whenever the
    // bound version changes, otherwise the file opened in the previous conversation
    // stays docked on the right of the new one (F035 stale-preview bug).
    useEffect(() => {
        setPreviewFile(null);
        setSourcePreview(null);
        setFullscreen(false);
        setOpen(false);
    }, [versionId]);

    /** Open the panel on the file list (entry button). */
    const openWorkspace = () => {
        setPreviewFile(null);
        setSourcePreview(null);
        setFullscreen(false);
        setOpen(true);
    };

    /** Close the whole panel (list X or preview Close); entry button returns.
     * Keep previewFile as-is so a preview collapses while still showing the file
     * instead of flashing back to the list mid-animation; openWorkspace (and the
     * versionId reset above) restore the list view on the next open. */
    const closeWorkspace = () => {
        setSourcePreview(null);
        setFullscreen(false);
        setOpen(false);
    };

    /** Preview a file in place. html artifacts still open in the standalone tab
     *  (needs versionId to resolve the MinIO object key into a presigned link). */
    const openPreview = (file: ArtifactFile) => {
        if (isHtmlArtifact(file)) {
            openHtmlArtifactViewer(file, versionId);
            return;
        }
        setOpen(true);
        setSourcePreview(null);
        setPreviewFile(file);
    };

    /** Back from preview to the file list (ArrowLeft); keeps the panel open. */
    const backToList = () => {
        setPreviewFile(null);
        setSourcePreview(null);
        setFullscreen(false);
    };

    const toggleFullscreen = () => setFullscreen((v) => !v);

    /** F071: show a cited source beside the report; a new citation replaces it. */
    const openSource = useCallback((preview: SourcePreview) => setSourcePreview(preview), []);
    /** F071: collapse only the source (its own button / Esc); the report stays. */
    const closeSource = useCallback(() => setSourcePreview(null), []);

    return {
        open,
        previewFile,
        fullscreen,
        openWorkspace,
        closeWorkspace,
        openPreview,
        backToList,
        toggleFullscreen,
        setFullscreen,
        sourcePreview,
        openSource,
        closeSource,
        /** Report + source side by side — ChatView hands the chat column's width over. */
        comparing: open && !!previewFile && !!sourcePreview,
    };
}
