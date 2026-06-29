/**
 * F035 Track H (P4): workspace drawer (spec §5, fig 9) — right-side sheet
 * titled "Workspace" listing every output artifact; clicking a row switches
 * the right area to the file preview panel (handled by useArtifactsPanel).
 */
import { Eye } from 'lucide-react';
import FileIcon from '~/components/ui/icon/File';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '~/components/ui/Sheet';
import { useLocalize } from '~/hooks';
import { EmptyStateIllustration } from '~/components/illustrations';
import { type ArtifactFile, getFileExtension } from './artifactUtils';

interface WorkspaceDrawerProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    files: ArtifactFile[];
    onPreview: (file: ArtifactFile) => void;
}

export function WorkspaceDrawer({ open, onOpenChange, files, onPreview }: WorkspaceDrawerProps) {
    const localize = useLocalize();

    // Split into the two product zones: user-uploaded sources vs agent deliverables.
    const uploaded = files.filter((f) => f.source === 'upload');
    const generated = files.filter((f) => f.source !== 'upload');

    const renderRow = (file: ArtifactFile) => (
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
            <span className="min-w-0 flex-1 truncate text-sm text-gray-800">{file.file_name}</span>
            <Eye size={15} className="invisible shrink-0 text-gray-400 group-hover:visible" />
        </div>
    );

    const renderGroup = (titleKey: string, group: ArtifactFile[]) =>
        group.length > 0 && (
            <div className="pt-2">
                <div className="px-2 py-1.5 text-xs font-medium text-gray-400">{localize(titleKey)}</div>
                {group.map(renderRow)}
            </div>
        );

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent className="w-[480px] sm:max-w-[480px]">
                <SheetHeader className="border-b border-gray-100 px-5 py-4">
                    <SheetTitle className="text-base">{localize('com_linsight_workspace')}</SheetTitle>
                </SheetHeader>
                <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-3 pb-6">
                    {renderGroup('com_linsight_workspace_uploaded', uploaded)}
                    {renderGroup('com_linsight_workspace_generated', generated)}
                    {!files.length && (
                        <div className="flex flex-col items-center justify-center py-10 text-center">
                            <EmptyStateIllustration className="mb-4 size-[120px] opacity-90" />
                            <p className="text-[14px] font-normal text-[#999999]">{localize('com_linsight_workspace_empty')}</p>
                        </div>
                    )}
                </div>
            </SheetContent>
        </Sheet>
    );
}
