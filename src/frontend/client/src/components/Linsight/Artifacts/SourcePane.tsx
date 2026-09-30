/**
 * F071: the cited source file shown beside the report in the task-mode
 * workspace. It replaces the floating CitationDocumentPreviewDrawer there, which
 * covered the report it was supposed to be checked against.
 *
 * Locating the cited passage: PDFs keep the bbox highlight inside PdfViewer.
 * docx / md / txt have no coordinates (ingestion turns them into markdown), so
 * the chunk text is matched against the rendered viewer DOM (citationLocate).
 * When that fails — or for spreadsheets, which have no passage to land on — the
 * quoted text is shown above the file instead of silently opening at the top.
 */
import { Outlined } from 'bisheng-icons';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CitationDocumentPreviewContent, type CitationDocumentPreviewState } from '~/components/Chat/Messages/Content/CitationDocumentPreviewDrawer';
import {
    getCitationDocumentName,
    getCitationItem,
    resolveCitationDownloadUrl,
    toAbsolutePreviewUrl,
} from '~/components/Chat/Messages/Content/citationUtils';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { clearCitedHighlight, highlightCitedText } from './citationLocate';

type LocateState = 'pending' | 'found' | 'missed' | 'native';

/** Viewers that highlight on their own (bbox) or render media — nothing to match. */
const NATIVE_LOCATE_TYPES = new Set(['pdf', 'mp3', 'wav', 'm4a', 'mp4', 'mov', 'webm', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp']);
/** Tables have no passage to land on; show the quote straight away. */
const QUOTE_ONLY_TYPES = new Set(['xlsx', 'xls', 'csv']);

const iconBtn =
    'flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-gray-100 disabled:cursor-not-allowed disabled:text-text-4';

export interface SourceOccurrence {
    /** 1-based position among the report's citations of this same file. */
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

export function SourcePane({ preview, occurrence, onStep, onClose, onBackToReport }: SourcePaneProps) {
    const localize = useLocalize();
    const bodyRef = useRef<HTMLDivElement>(null);
    const [fileType, setFileType] = useState('');
    const [locate, setLocate] = useState<LocateState>('pending');
    const [downloadUrl, setDownloadUrl] = useState('');
    const { detail } = preview;
    const fileName = getCitationDocumentName(detail);

    // The chunk texts this citation points at (file-level clicks carry several).
    const chunks = useMemo(() => {
        const ids = preview.itemIds?.length ? preview.itemIds : [preview.itemId];
        return ids
            .map((id) => getCitationItem(detail, id))
            .map((item) => item?.content || item?.snippet || '')
            .filter(Boolean) as string[];
    }, [detail, preview.itemId, preview.itemIds]);

    // A different file remounts the viewer; forget the old type until it resolves.
    const documentKey = detail.citationId;
    useEffect(() => {
        setFileType('');
    }, [documentKey]);

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

    // Locate the cited text once the viewer has rendered. Stepping to another
    // passage of the same file keeps the DOM, so try immediately; a new file
    // renders asynchronously (fetch + mammoth / markdown), so watch for it.
    useEffect(() => {
        const root = bodyRef.current;
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
            setLocate('missed');
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
    }, [chunks, fileType]);

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

            {locate === 'missed' && chunks.length > 0 && (
                <div className="max-h-40 shrink-0 overflow-y-auto border-b border-border-base bg-orange-50 px-4 py-3 text-[13px] scrollbar-os">
                    <p className="mb-1 font-medium text-orange-600">{localize('com_citation.locate_missed')}</p>
                    <p className="whitespace-pre-wrap break-words border-l-2 border-border-base pl-2 text-text-2">
                        {chunks.join('\n\n')}
                    </p>
                </div>
            )}

            <div
                ref={bodyRef}
                className={cn(
                    'flex min-h-0 flex-1 flex-col overflow-hidden',
                    // Cited blocks: the same light brand tint the docked report uses for
                    // selection, with a left rule so it still reads on tinted table cells.
                    // Literal class (Tailwind can't see an interpolated one); the
                    // attribute name is CITE_HIT_ATTR.
                    '[&_[data-cite-hit]]:bg-blue-500/[0.07] [&_[data-cite-hit]]:shadow-[inset_2px_0_0_rgb(var(--brand-500))]',
                )}
            >
                <CitationDocumentPreviewContent key={documentKey} preview={preview} compactMode onFileTypeResolved={setFileType} />
            </div>
        </div>
    );
}
