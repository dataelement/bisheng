/**
 * F035: INLINE workspace panel for the chat-embedded task mode. Replaces the
 * legacy right-side drawer (WorkspaceDrawer + FilePreviewPanel) with a card
 * docked on the right of the chat `main`. Two modes share the same area:
 *   - list:    "工作区" header + close; flat file list.
 *   - preview: ArrowLeft back / "文件" / Download / fullscreen toggle / Close,
 *              with the file rendered in place. Fullscreen expands within `main`
 *              (the chat column is hidden by the parent), not the browser.
 * State lives in useWorkspacePanel; the parent (ChatView) owns the layout.
 */
import { Outlined } from 'bisheng-icons';
import FileIcon from '~/components/ui/icon/File';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { type ArtifactFile, downloadArtifactFile, getFileExtension } from './artifactUtils';
import { PreviewBody } from './PreviewBody';

interface WorkspacePanelProps {
    files: ArtifactFile[];
    versionId: string;
    /** null → file-list view; set → in-place preview of this file */
    previewFile: ArtifactFile | null;
    fullscreen: boolean;
    onPreview: (file: ArtifactFile) => void;
    onBack: () => void;
    onClose: () => void;
    onToggleFullscreen: () => void;
}

const iconBtn =
    'flex h-7 w-7 items-center justify-center rounded-md text-[#8C8C8C] transition-colors hover:bg-gray-100 hover:text-[#335CFF]';

export function WorkspacePanel({
    files,
    versionId,
    previewFile,
    fullscreen,
    onPreview,
    onBack,
    onClose,
    onToggleFullscreen,
}: WorkspacePanelProps) {
    const localize = useLocalize();

    const renderRow = (file: ArtifactFile) => (
        <div
            key={file.file_id || file.file_url}
            role="button"
            tabIndex={0}
            className="group flex cursor-pointer items-center gap-2.5 rounded-lg py-2 hover:bg-[#F7F7F7]"
            onClick={() => onPreview(file)}
            onKeyDown={(e) => e.key === 'Enter' && onPreview(file)}
        >
            {/* File-type icon hidden for now; keep for an easy future re-enable. */}
            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any -- FileIcon accepts more types than its union */}
            {/* <FileIcon type={getFileExtension(file.file_name) as any} className="size-5 min-w-5" /> */}
            <span className="min-w-0 flex-1 truncate text-sm text-[#212121] group-hover:text-[#335CFF]">
                {file.file_name}
            </span>
        </div>
    );

    const handleDownload = async () => {
        if (!previewFile) return;
        try {
            await downloadArtifactFile(previewFile, versionId);
        } catch (e) {
            console.error('artifact download failed:', e);
        }
    };

    return (
        <div
            className={cn(
                'flex h-full min-h-0 w-full flex-col overflow-hidden bg-[#FBFBFB]',
                // Fullscreen overlays the whole route viewport flush to the edges;
                // the card chrome (radius/border) only applies to the docked panel.
                !fullscreen && 'rounded-[12px] border border-[#ECECEC]',
            )}
        >
            {previewFile ? (
                <>
                    {/* preview toolbar */}
                    <div className="flex h-[52px] shrink-0 items-center gap-2 px-3">
                        <button type="button" aria-label={localize('com_linsight_back_to_workspace')} className={iconBtn} onClick={onBack}>
                            <Outlined.ArrowLeft className="size-4" />
                        </button>
                        <span className="min-w-0 flex-1 truncate text-sm text-[#212121]">
                            {localize('com_linsight_preview_file')}
                        </span>
                        <button type="button" aria-label={localize('com_linsight_download_to_view')} className={iconBtn} onClick={handleDownload}>
                            <Outlined.Download className="size-4" />
                        </button>
                        <button
                            type="button"
                            aria-label={localize(fullscreen ? 'com_linsight_exit_fullscreen' : 'com_linsight_fullscreen')}
                            className={iconBtn}
                            onClick={onToggleFullscreen}
                        >
                            {fullscreen ? (
                                <Outlined.CollapseTextInput className="size-4" />
                            ) : (
                                <Outlined.ExpandTextInput className="size-4" />
                            )}
                        </button>
                        <button type="button" aria-label={localize('com_ui_close')} className={iconBtn} onClick={onClose}>
                            <Outlined.Close className="size-4" />
                        </button>
                    </div>
                    {/* preview body — scrollbar-os: respect OS scrollbar setting */}
                    <div className="min-h-0 flex-1 overflow-y-auto scrollbar-os">
                        <PreviewBody file={previewFile} versionId={versionId} />
                    </div>
                </>
            ) : (
                <>
                    {/* list header */}
                    <div className="flex h-[52px] shrink-0 items-center justify-between px-4">
                        <span className="text-sm font-medium text-[#212121]">{localize('com_linsight_workspace')}</span>
                        <button type="button" aria-label={localize('com_ui_close')} className={iconBtn} onClick={onClose}>
                            <Outlined.Close className="size-4" />
                        </button>
                    </div>
                    {/* list body — overall padding 16px, 16px between rows */}
                    <div className="min-h-0 flex-1 overflow-y-auto scrollbar-os p-4">
                        {files.length ? (
                            <div className="flex flex-col gap-4">{files.map(renderRow)}</div>
                        ) : (
                            <div className="py-10 text-center text-sm text-gray-400">
                                {localize('com_linsight_workspace_empty')}
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    );
}
