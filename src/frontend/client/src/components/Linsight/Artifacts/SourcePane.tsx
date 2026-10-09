/**
 * F071: the cited source file shown beside the report in the task-mode
 * workspace. It replaces the floating CitationDocumentPreviewDrawer there, which
 * covered the report it was supposed to be checked against.
 *
 * Locating the cited passage (bbox for PDFs, text matching for docx / md / txt,
 * the quoted text when neither lands) lives in CitationDocumentPreviewContent,
 * shared with the daily-chat and knowledge-space previews.
 */
import { Outlined } from 'bisheng-icons';
import { useCallback, useEffect, useState } from 'react';
import { CitationDocumentPreviewContent, type CitationDocumentPreviewState } from '~/components/Chat/Messages/Content/CitationDocumentPreviewDrawer';
import {
    getCitationDocumentName,
    resolveCitationDownloadUrl,
    toAbsolutePreviewUrl,
} from '~/components/Chat/Messages/Content/citationUtils';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize } from '~/hooks';

const iconBtn =
    'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:text-text-4';

export interface SourceOccurrence {
    /** 1-based position among the distinct passages of this file the report cites. */
    index: number;
    total: number;
}

interface SourcePaneProps {
    preview: CitationDocumentPreviewState;
    occurrence: SourceOccurrence | null;
    onStep: (delta: 1 | -1) => void;
    onClose: () => void;
    /** Tabs layout (< 1024px): link back to the report instead of the collapse button. */
    onBackToReport?: () => void;
    /** Render the toolbar only; the document mounts once this turns false. */
    deferBody?: boolean;
}

function IconButton({ label, onClick, disabled, children }: {
    label: string;
    onClick: () => void;
    disabled?: boolean;
    children: React.ReactNode;
}) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <button type="button" aria-label={label} className={iconBtn} onClick={onClick} disabled={disabled}>
                    {children}
                </button>
            </TooltipTrigger>
            <TooltipContent>{label}</TooltipContent>
        </Tooltip>
    );
}

export function SourcePane({ preview, occurrence, onStep, onClose, onBackToReport, deferBody = false }: SourcePaneProps) {
    const localize = useLocalize();
    const [downloadUrl, setDownloadUrl] = useState('');
    const { detail } = preview;
    const fileName = getCitationDocumentName(detail);
    // A different file remounts the viewer.
    const documentKey = detail.citationId;

    useEffect(() => {
        let active = true;
        setDownloadUrl('');
        void resolveCitationDownloadUrl(detail).then((url) => {
            if (active) setDownloadUrl(toAbsolutePreviewUrl(url || ''));
        });
        return () => {
            active = false;
        };
    }, [detail]);

    const handleDownload = useCallback(() => {
        if (!downloadUrl) return;
        const link = document.createElement('a');
        link.href = downloadUrl;
        link.download = fileName;
        link.target = '_blank';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }, [downloadUrl, fileName]);

    const showStepper = !!occurrence && occurrence.total > 1;
    const showNavRow = showStepper || !!onBackToReport;

    return (
        <div className="flex h-full min-h-0 min-w-0 flex-col bg-white">
            <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border-base px-4">
                <Outlined.File className="size-4 shrink-0 text-blue-500" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium text-text-1" title={fileName}>
                    {fileName}
                </span>
                <IconButton label={localize('com_knowledge.download_file')} onClick={handleDownload} disabled={!downloadUrl}>
                    <Outlined.Download className="size-4" />
                </IconButton>
                {!onBackToReport && (
                    <IconButton label={localize('com_citation.collapse_source')} onClick={onClose}>
                        <Outlined.RightSidebar className="size-4" />
                    </IconButton>
                )}
            </div>

            {showNavRow && (
                <div className="flex h-10 shrink-0 items-center gap-1 border-b border-border-base px-3 text-[13px] text-text-2">
                    {onBackToReport && (
                        <button
                            type="button"
                            className="flex h-7 items-center gap-1 rounded-lg px-2 hover:bg-gray-100"
                            onClick={onBackToReport}
                        >
                            <Outlined.ArrowLeft className="size-4" />
                            {localize('com_citation.back_to_report')}
                        </button>
                    )}
                    <span className="flex-1" />
                    {showStepper && (
                        <>
                            <IconButton label={localize('com_citation.prev_occurrence')} onClick={() => onStep(-1)}>
                                <Outlined.Left className="size-4" />
                            </IconButton>
                            <span className="px-1 tabular-nums">
                                {localize('com_citation.occurrence', { index: occurrence.index, total: occurrence.total })}
                            </span>
                            <IconButton label={localize('com_citation.next_occurrence')} onClick={() => onStep(1)}>
                                <Outlined.Right className="size-4" />
                            </IconButton>
                        </>
                    )}
                </div>
            )}

            <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                {!deferBody && <CitationDocumentPreviewContent key={documentKey} preview={preview} compactMode />}
            </div>
        </div>
    );
}
