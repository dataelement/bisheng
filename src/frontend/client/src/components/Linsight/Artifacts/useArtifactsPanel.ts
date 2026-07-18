/**
 * F035 Track H (P4): state for the single right-side area shared by the
 * workspace drawer and the file preview panel — mutually exclusive, with
 * "back to workspace" when the preview was opened from the drawer.
 * Plain local state: the panel only lives inside the ExecutionFlow tree,
 * so no Recoil atom is needed.
 */
import { useEffect, useState } from 'react';
import { openHtmlArtifactViewer, type ArtifactFile } from './artifactUtils';

export function useArtifactsPanel(versionId: string) {
    const [workspaceOpen, setWorkspaceOpen] = useState(false);
    const [previewFile, setPreviewFile] = useState<ArtifactFile | null>(null);
    const [fromWorkspace, setFromWorkspace] = useState(false);

    // Sop/index.tsx is KeepAlive-cached and lets the user switch task versions
    // (Header version selector) in place. Reset the workspace/preview area when the
    // bound version changes so a file opened on one version doesn't stay open after
    // switching to another (same stale-preview class as useWorkspacePanel).
    useEffect(() => {
        setPreviewFile(null);
        setFromWorkspace(false);
        setWorkspaceOpen(false);
    }, [versionId]);

    const openWorkspace = () => {
        setPreviewFile(null);
        setWorkspaceOpen(true);
    };

    const openPreview = (file: ArtifactFile, viaWorkspace = false) => {
        // html artifacts open in the standalone sandboxed viewer tab (the side
        // panel can't render a full HTML document); needs versionId to resolve
        // the MinIO object key into a presigned link.
        if (file.file_name?.toLowerCase().endsWith('.html')) {
            openHtmlArtifactViewer(file, versionId);
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
