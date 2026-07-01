/**
 * F035 Track H (P4): file preview panel (spec §5, fig 10) — wide right-side
 * sheet for the full-page /linsight view. Toolbar: back-to-workspace (when
 * opened from the drawer) / file name / save-as / close. The body delegates to
 * the shared PreviewBody so this surface and the inline WorkspacePanel render
 * identical content (md / txt / image / docx·pdf·xls·xlsx·csv viewer / download
 * fallback) from a single source of truth.
 */
import { Outlined } from 'bisheng-icons';
import { ChevronLeft } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { Sheet, SheetContent } from '~/components/ui/Sheet';
import { useLocalize } from '~/hooks';
import { type ArtifactFile, getFileExtension } from './artifactUtils';
import { PreviewBody } from './PreviewBody';
import { SaveAsButton } from './SaveAsButton';

interface FilePreviewPanelProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    file: ArtifactFile | null;
    versionId: string;
    /** present when the preview was opened from the workspace drawer */
    onBack?: () => void;
}

export function FilePreviewPanel({ open, onOpenChange, file, versionId, onBack }: FilePreviewPanelProps) {
    const localize = useLocalize();

    if (!file) return null;

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            {/* hideClose: the built-in lucide X is replaced by a bisheng-icon close
                in the toolbar so it matches the download button's icon/size/color. */}
            <SheetContent hideClose className="w-[800px] sm:max-w-[800px]">
                {/* toolbar */}
                <div className="flex items-center gap-2 border-b border-gray-100 py-3 pl-5 pr-5">
                    {onBack && (
                        <button
                            type="button"
                            aria-label={localize('com_linsight_back_to_workspace')}
                            className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100"
                            onClick={onBack}
                        >
                            <ChevronLeft size={16} />
                        </button>
                    )}
                    {/* eslint-disable-next-line @typescript-eslint/no-explicit-any -- FileIcon accepts more types than its union */}
                    <FileIcon type={getFileExtension(file.file_name) as any} className="size-4 min-w-4" />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-900">
                        {file.file_name}
                    </span>
                    <SaveAsButton file={file} versionId={versionId} iconOnly />
                    <button
                        type="button"
                        aria-label={localize('com_ui_close')}
                        className="rounded-md p-1 text-[#8C8C8C] transition-colors hover:text-blue-500"
                        onClick={() => onOpenChange(false)}
                    >
                        <Outlined.Close className="size-[18px]" />
                    </button>
                </div>
                {/* content */}
                {/* scrollbar-os: opt out of the forced custom webkit scrollbar so the
                    OS setting (auto-hide vs always-on) is respected (see style.css). */}
                <div className="min-h-0 flex-1 overflow-y-auto scrollbar-os">
                    <PreviewBody file={file} versionId={versionId} />
                </div>
            </SheetContent>
        </Sheet>
    );
}
