/**
 * F035 Track H (P4): state for the single right-side area shared by the
 * workspace drawer and the file preview panel — mutually exclusive, with
 * "back to workspace" when the preview was opened from the drawer.
 * Plain local state: the panel only lives inside the ExecutionFlow tree,
 * so no Recoil atom is needed.
 */
import { useState } from 'react';
import type { ArtifactFile } from './artifactUtils';

export function useArtifactsPanel() {
    const [workspaceOpen, setWorkspaceOpen] = useState(false);
    const [previewFile, setPreviewFile] = useState<ArtifactFile | null>(null);
    const [fromWorkspace, setFromWorkspace] = useState(false);

    const openWorkspace = () => {
        setPreviewFile(null);
        setWorkspaceOpen(true);
    };

    const openPreview = (file: ArtifactFile, viaWorkspace = false) => {
        // html artifacts open in the standalone viewer tab (same as legacy)
        if (file.file_name?.toLowerCase().endsWith('.html')) {
            window.open(`${__APP_ENV__.BASE_URL}/html?url=${encodeURIComponent(file.file_url)}`, '_blank');
            return;
        }
        setWorkspaceOpen(false);
        setFromWorkspace(viaWorkspace);
        setPreviewFile(file);
    };

    const backToWorkspace = () => {
        setPreviewFile(null);
        setFromWorkspace(false);
        setWorkspaceOpen(true);
    };

    const closePreview = () => {
        setPreviewFile(null);
        setFromWorkspace(false);
    };

    return {
        workspaceOpen,
        setWorkspaceOpen,
        previewFile,
        fromWorkspace,
        openWorkspace,
        openPreview,
        backToWorkspace,
        closePreview,
    };
}
