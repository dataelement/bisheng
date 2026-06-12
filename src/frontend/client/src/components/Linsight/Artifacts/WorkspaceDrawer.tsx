/**
 * F035 Track H (P4): workspace drawer (spec §5, fig 9) — right-side sheet
 * titled "Workspace" listing every output artifact; clicking a row switches
 * the right area to the file preview panel (handled by useArtifactsPanel).
 */
import { Eye } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '~/components/ui/Sheet';
import { useLocalize } from '~/hooks';
import { type ArtifactFile, getFileExtension } from './artifactUtils';

interface WorkspaceDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    files: ArtifactFile[];
    onPreview: (file: ArtifactFile) => void;
}

export function WorkspaceDrawer({ open, onOpenChange, files, onPreview }: WorkspaceDrawerProps) {
    const localize = useLocalize();

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="w-[480px] sm:max-w-[480px]">
                <SheetHeader className="border-b border-gray-100 px-5 py-4">
                    <SheetTitle className="text-base">{localize('com_linsight_workspace')}</SheetTitle>
                </SheetHeader>
                <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-3 pb-6">
                    {files.map((file) => (
                        <div
                            key={file.file_id || file.file_url}
                            role="button"
                            tabIndex={0}
                            className="group flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2.5 hover:bg-gray-50"
                            onClick={() => onPreview(file)}
                            onKeyDown={(e) => e.key === 'Enter' && onPreview(file)}
                        >
                            {/* eslint-disable-next-line @typescript-eslint/no-explicit-any -- FileIcon accepts more types than its union */}
                            <FileIcon type={getFileExtension(file.file_name) as any} className="size-5 min-w-5" />
                            <span className="min-w-0 flex-1 truncate text-sm text-gray-800">
                                {file.file_name}
                            </span>
                            <Eye size={15} className="invisible shrink-0 text-gray-400 group-hover:visible" />
                        </div>
                    ))}
                    {!files.length && (
                        <div className="py-10 text-center text-sm text-gray-400">
                            {localize('com_linsight_workspace_empty')}
                        </div>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    );
}
