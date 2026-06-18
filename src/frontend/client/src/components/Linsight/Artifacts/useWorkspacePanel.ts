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
 */
import { useState } from 'react';
import type { ArtifactFile } from './artifactUtils';

export function useWorkspacePanel() {
    const [open, setOpen] = useState(false);
    const [previewFile, setPreviewFile] = useState<ArtifactFile | null>(null);
    const [fullscreen, setFullscreen] = useState(false);

    /** Open the panel on the file list (entry button). */
    const openWorkspace = () => {
        setPreviewFile(null);
        setFullscreen(false);
        setOpen(true);
    };

    /** Close the whole panel (list X or preview Close); entry button returns. */
    const closeWorkspace = () => {
        setPreviewFile(null);
        setFullscreen(false);
        setOpen(false);
    };

    /** Preview a file in place. html artifacts still open in the standalone tab. */
    const openPreview = (file: ArtifactFile) => {
        if (file.file_name?.toLowerCase().endsWith('.html')) {
            window.open(`${__APP_ENV__.BASE_URL}/html?url=${encodeURIComponent(file.file_url)}`, '_blank');
            return;
        }
        setOpen(true);
        setPreviewFile(file);
    };

    /** Back from preview to the file list (ArrowLeft); keeps the panel open. */
    const backToList = () => {
        setPreviewFile(null);
        setFullscreen(false);
    };

    const toggleFullscreen = () => setFullscreen((v) => !v);

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
    };
}
