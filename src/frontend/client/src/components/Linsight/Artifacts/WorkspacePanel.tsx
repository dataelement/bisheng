/**
 * F035: INLINE workspace panel for the chat-embedded task mode. Replaces the
 * legacy right-side drawer (WorkspaceDrawer + FilePreviewPanel) with a card
 * docked on the right of the chat `main`. Three modes share the same area:
 *   - list:    "工作区" header + close; flat file list.
 *   - preview: ArrowLeft back / "文件" / Download / fullscreen toggle / Close,
 *              with the file rendered in place. Fullscreen expands within `main`
 *              (the chat column is hidden by the parent), not the browser.
 *   - compare (F071): clicking a document citation in the report opens the
 *              cited file BESIDE the report (split layout) or behind a
 *              report / source switch (tabs layout, < 1024px) — never on top of
 *              the report it is being checked against.
 * State lives in useWorkspacePanel; the parent (ChatView) owns the layout.
 */
import { Segmented } from '@bisheng/ui';
import { Outlined } from 'bisheng-icons';
import { useEffect, useState } from 'react';
import type { ChatCitation } from '~/api/chatApi';
import { Tooltip, TooltipContent, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize } from '~/hooks';
import { EmptyStateIllustration } from '~/components/illustrations';
import { cn } from '~/utils';
import { type ArtifactFile } from './artifactUtils';
import { NewTabHint } from './NewTabHint';
import { PreviewBody } from './PreviewBody';
import { SaveAsButton } from './SaveAsButton';
import { SourcePane } from './SourcePane';
import { useCompareSplit } from './useCompareSplit';
import { useSourceOccurrences } from './useSourceOccurrences';
import type { SourcePreview } from './useWorkspacePanel';

interface WorkspacePanelProps {
    files: ArtifactFile[];
    versionId: string;
    citations?: ChatCitation[] | null;
    messageId?: string;
    /** null → file-list view; set → in-place preview of this file */
    previewFile: ArtifactFile | null;
    fullscreen: boolean;
    /** Hide the fullscreen toggle — used on mobile, where the panel is already a
     *  full-screen overlay / drawer and the toggle would be meaningless. */
    hideFullscreenToggle?: boolean;
    /** F071: cited source shown with the report; null → report only. */
    sourcePreview?: SourcePreview | null;
    /** F071: 'split' puts the source beside the report; 'tabs' (narrow screens)
     *  switches between them because two columns would each be too narrow. */
    compareLayout?: 'split' | 'tabs';
    onOpenSource?: (preview: SourcePreview) => void;
    onCloseSource?: () => void;
    onPreview: (file: ArtifactFile) => void;
    onBack: () => void;
    onClose: () => void;
    onToggleFullscreen: () => void;
}

const iconBtn =
    'flex h-7 w-7 items-center justify-center rounded-lg text-text-3 transition-colors hover:bg-gray-100';

type CompareTab = 'report' | 'source';

export function WorkspacePanel({
    files,
    versionId,
    citations,
    messageId,
    previewFile,
    fullscreen,
    hideFullscreenToggle,
    sourcePreview = null,
    compareLayout = 'split',
    onOpenSource,
    onCloseSource,
    onPreview,
    onBack,
    onClose,
    onToggleFullscreen,
}: WorkspacePanelProps) {
    const localize = useLocalize();
    const comparing = !!previewFile && !!sourcePreview;
    const tabsLayout = comparing && compareLayout === 'tabs';
    const [tab, setTab] = useState<CompareTab>('report');
    const split = useCompareSplit();
    const occurrences = useSourceOccurrences({ citations, sourcePreview, onOpenSource });

    // Opening (or replacing) a source brings it to front in the tabs layout.
    useEffect(() => {
        setTab(sourcePreview ? 'source' : 'report');
    }, [sourcePreview]);

    // Esc collapses the innermost layer only: the source, never the whole workspace.
    useEffect(() => {
        if (!comparing || !onCloseSource) return undefined;
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key !== 'Escape' || e.defaultPrevented) return;
            const target = e.target as HTMLElement | null;
            if (target?.closest('input,textarea,[contenteditable="true"]')) return;
            onCloseSource();
        };
        document.addEventListener('keydown', handleKeyDown);
        return () => document.removeEventListener('keydown', handleKeyDown);
    }, [comparing, onCloseSource]);

    const handleTabChange = (next: string) => {
        setTab(next as CompareTab);
        // Back on the report: land on the citation being checked, not the top.
        if (next === 'report') occurrences.revealActive();
    };

    const renderRow = (file: ArtifactFile) => (
        <div
            key={file.file_id || file.file_url}
            role="button"
            tabIndex={0}
            /* has-[[data-state=open]]: hold the hover look while this row's own
               "另存为" menu is open — the pointer is on the panel by then. */
            className="group/row flex cursor-pointer items-center justify-between gap-2 rounded-lg py-2 pl-1 pr-1 hover:bg-[#F7F7F7] has-[[data-state=open]]:bg-[#F7F7F7]"
            onClick={() => onPreview(file)}
            onKeyDown={(e) => e.key === 'Enter' && onPreview(file)}
        >
            {/* File-type icon hidden for now; keep for an easy future re-enable. */}
            { }
            {/* <FileIcon type={getFileExtension(file.file_name) as any} className="size-5 min-w-5" /> */}
            <span className="flex min-w-0 items-center gap-1.5">
                <span className="min-w-0 truncate text-sm text-text-1 group-hover/row:text-blue-500 group-has-[[data-state=open]]/row:text-blue-500">
                    {file.file_name}
                </span>
                <NewTabHint file={file} />
            </span>
            {/* Always-visible worded action at the row's end — same treatment as
                the delivery card's rows, so the two file lists read as one. */}
            <SaveAsButton file={file} versionId={versionId} variant="labeled" citations={citations} />
        </div>
    );

    const reportPane = previewFile && (
        <div
            className={cn(
                'flex min-h-0 min-w-0 flex-col',
                // Split: fixed width from the splitter. Tabs on the source view:
                // only the toolbar (with the switch) stays, the body is hidden.
                (comparing && !tabsLayout) || (tabsLayout && tab === 'source') ? 'shrink-0' : 'flex-1',
            )}
            style={comparing && !tabsLayout ? split.leftStyle : undefined}
        >
            {/* preview toolbar */}
            <div className="flex h-12 shrink-0 items-center gap-2 px-4">
                <button type="button" aria-label={localize('com_linsight_back_to_workspace')} className={iconBtn} onClick={onBack}>
                    <Outlined.ArrowLeft className="size-4" />
                </button>
                {tabsLayout ? (
                    <div className="flex min-w-0 flex-1 justify-center">
                        <Segmented
                            size="small"
                            value={tab}
                            onChange={handleTabChange}
                            options={[
                                { value: 'report', label: localize('com_citation.tab_report') },
                                { value: 'source', label: localize('com_citation.tab_source') },
                            ]}
                        />
                    </div>
                ) : (
                    <span
                        className="min-w-0 flex-1 truncate text-sm text-text-1"
                        title={previewFile.file_name}
                    >
                        {previewFile.file_name || localize('com_linsight_preview_file')}
                    </span>
                )}
                {/* Same action as the file rows, so a markdown deliverable
                    offers md / PDF / Docx here too instead of only the raw
                    source — the two surfaces are one click apart. */}
                {!tabsLayout && <SaveAsButton file={previewFile} versionId={versionId} variant="toolbar" citations={citations} />}
                {!hideFullscreenToggle && (
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
                )}
                {/* F071: this X closes the report AND its source; the source pane
                    has its own, differently drawn, collapse button. */}
                <Tooltip>
                    <TooltipTrigger asChild>
                        <button type="button" aria-label={localize('com_citation.close_workspace')} className={iconBtn} onClick={onClose}>
                            <Outlined.Close className="size-4" />
                        </button>
                    </TooltipTrigger>
                    <TooltipContent>{localize('com_citation.close_workspace')}</TooltipContent>
                </Tooltip>
            </div>
            {/* preview body — scrollbar-os: respect OS scrollbar setting. Kept
                mounted on the source tab so the report keeps its place. */}
            <div
                ref={occurrences.reportRef}
                onClickCapture={occurrences.handleReportClickCapture}
                className={cn(
                    'min-h-0 flex-1 overflow-y-auto scrollbar-os',
                    // The citation being checked keeps the badge's open-state tint (组件-Badge徽标 §5).
                    '[&_[data-compare-active]]:bg-blue-100',
                    tabsLayout && tab === 'source' && 'hidden',
                )}
            >
                <PreviewBody
                    file={previewFile}
                    versionId={versionId}
                    fileList={files}
                    citations={citations}
                    messageId={messageId}
                    onArtifactPreview={onPreview}
                    onOpenSource={onOpenSource ? occurrences.openFromReport : undefined}
                />
            </div>
        </div>
    );

    return (
        <div
            className={cn(
                'flex h-full min-h-0 w-full flex-col overflow-hidden bg-[#FBFBFB]',
                // Fullscreen overlays the whole route viewport flush to the edges;
                // the card chrome (radius/border) only applies to the docked panel.
                !fullscreen && 'rounded-lg border border-border-base',
            )}
        >
            {previewFile ? (
                <div ref={split.containerRef} className={cn('flex min-h-0 flex-1', tabsLayout && 'flex-col')}>
                    {reportPane}
                    {comparing && sourcePreview && !tabsLayout && (
                        <div
                            role="separator"
                            aria-orientation="vertical"
                            aria-valuenow={Math.round(split.ratio * 100)}
                            tabIndex={0}
                            className="group relative z-10 -mx-1 w-2 shrink-0 cursor-col-resize touch-none outline-none"
                            onPointerDown={split.handlePointerDown}
                            onKeyDown={split.handleKeyDown}
                        >
                            <span
                                className={cn(
                                    'absolute inset-y-0 left-1/2 w-px -translate-x-1/2 bg-border-base transition-colors',
                                    'group-hover:w-0.5 group-hover:bg-blue-500 group-focus-visible:w-0.5 group-focus-visible:bg-blue-500',
                                    split.dragging && 'w-0.5 bg-blue-500',
                                )}
                            />
                        </div>
                    )}
                    {comparing && sourcePreview && (!tabsLayout || tab === 'source') && (
                        <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', !tabsLayout && split.rightClassName)}>
                            <SourcePane
                                preview={sourcePreview}
                                occurrence={occurrences.occurrence}
                                onStep={occurrences.step}
                                onClose={() => onCloseSource?.()}
                                onBackToReport={tabsLayout ? () => handleTabChange('report') : undefined}
                            />
                        </div>
                    )}
                </div>
            ) : (
                <>
                    {/* list header */}
                    <div className="flex h-12 shrink-0 items-center justify-between px-4">
                        <span className="text-sm font-medium text-text-1">{localize('com_linsight_workspace')}</span>
                        <button type="button" aria-label={localize('com_ui_close')} className={iconBtn} onClick={onClose}>
                            <Outlined.Close className="size-4" />
                        </button>
                    </div>
                    {/* list body — 4px top, 16px bottom, 12px left/right; 8px between rows */}
                    <div className="min-h-0 flex-1 overflow-y-auto scrollbar-os px-3 pt-1 pb-4">
                        {files.length ? (
                            <div className="flex flex-col gap-2">{files.map(renderRow)}</div>
                        ) : (
                            <div className="flex h-full flex-col items-center justify-center text-center">
                                <EmptyStateIllustration className="mb-4 size-[120px]" />
                                <p className="text-[14px] font-normal text-text-3">{localize('com_linsight_workspace_empty')}</p>
                            </div>
                        )}
                    </div>
                </>
            )}
        </div>
    );
}
