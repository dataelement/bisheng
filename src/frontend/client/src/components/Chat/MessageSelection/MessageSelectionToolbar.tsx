/**
 * F028 — Bottom-fixed operation bar that appears when the conversation
 * export selection mode is active.
 *
 * Two layouts driven by viewport: PC (≥768px) shows the four format buttons
 * inline; H5 collapses them into a single "Export to local" button that
 * opens <ExportFormatSheet> via the ``onExportToLocal`` callback (parent
 * owns the sheet so it can portal cleanly out of the toolbar's z-context).
 *
 * Selection-state writes go through useMessageSelection (toggle/selectAll/
 * exit). Side effects (HTTP, modals) are reported via callbacks so the
 * toolbar stays presentational and easy to unit-test.
 */

import { useCallback, useState, type ComponentType } from 'react';
import { Download, X } from 'lucide-react';
import { Outlined } from 'bisheng-icons';
import {
    type ExportFormat,
    exportMessagesApi,
    triggerBrowserDownload,
} from '~/api/messageExport';
import { translateApiErrorMessage } from '~/api/request';
import { Button } from '~/components/ui/Button';
import { Checkbox } from '~/components/ui/Checkbox';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import { useLocalize } from '~/hooks';
import { type SelectableMessage, useMessageSelection } from '~/hooks/useMessageSelection';
import { useToastContext } from '~/Providers';
import { NotificationSeverity } from '~/common';
import { cn } from '~/utils';

export interface MessageSelectionToolbarProps {
    /** Current chat id — used to scope selection and submit IDs. */
    chatId: string;
    /** Visible message list (drives selectedIds materialization). */
    messages: readonly SelectableMessage[];
    /** Open the H5 export-format bottom sheet (H5 only; ignored on PC). */
    onExportToLocal?: () => void;
    /** Open the AddToKnowledgeModal target picker. */
    onImportToKnowledge: () => void;
}

/**
 * Map the raw frontend messageId string (which is what TMessage carries) to
 * the integer id the backend stores. F028 backend expects ``message_ids:
 * list[int]`` (chat_message.id). The frontend TMessage.messageId is the
 * conversational id (often equal to ``chat_message.id`` for non-anonymous
 * messages, but stored as string).
 */
function _toBackendIds(ids: string[]): number[] {
    const out: number[] = [];
    for (const raw of ids) {
        const n = Number.parseInt(raw, 10);
        if (Number.isFinite(n)) out.push(n);
    }
    return out;
}

export function MessageSelectionToolbar({
    chatId,
    messages,
    onExportToLocal,
    onImportToKnowledge,
}: MessageSelectionToolbarProps) {
    const localize = useLocalize();
    const isMobile = usePrefersMobileLayout();
    const { showToast } = useToastContext();
    const {
        state,
        setGlobalSelectAll,
        exitSelectionMode,
        getSelectedIds,
        isOverLimit,
    } = useMessageSelection();
    const [exporting, setExporting] = useState<ExportFormat | null>(null);

    const handleExport = useCallback(
        async (format: ExportFormat) => {
            const ids = getSelectedIds(messages);
            if (!ids.length) {
                showToast({
                    message: localize('workstation.messageExport.noSelection') ?? '请先选择消息',
                    severity: NotificationSeverity.WARNING,
                });
                return;
            }
            if (isOverLimit(messages)) {
                showToast({
                    message: localize('workstation.messageExport.batchLimit'),
                    severity: NotificationSeverity.WARNING,
                });
                return;
            }
            setExporting(format);
            try {
                const file = await exportMessagesApi({
                    chatId,
                    messageIds: _toBackendIds(ids),
                    format,
                });
                triggerBrowserDownload(file);
            } catch (err: any) {
                showToast({
                    message:
                        translateApiErrorMessage({ status_code: err?.status_code, status_message: err?.status_message })
                        || localize('workstation.messageExport.renderFailed'),
                    severity: NotificationSeverity.ERROR,
                });
                // The error envelope is already logged by the axios interceptor;
                // we surface the user-facing message and leave the trace to it.
            } finally {
                setExporting(null);
            }
        },
        [chatId, messages, getSelectedIds, isOverLimit, showToast, localize],
    );

    const handleImport = useCallback(() => {
        const ids = getSelectedIds(messages);
        if (!ids.length) {
            showToast({
                message: localize('workstation.messageExport.noSelection') ?? '请先选择消息',
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        if (isOverLimit(messages)) {
            showToast({
                message: localize('workstation.messageExport.batchLimit'),
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        onImportToKnowledge();
    }, [messages, getSelectedIds, isOverLimit, showToast, localize, onImportToKnowledge]);

    // Only render the bar when selection mode is active for THIS chat — the
    // hook guards but we double-check to be defensive against stale mounts.
    if (!state.active || state.chatId !== chatId) return null;

    // ─── Render ────────────────────────────────────────────────────────

    const selectAllChecked = state.globalSelectAllOn;
    type FormatButton = {
        format: ExportFormat;
        labelKey: string;
        icon: ComponentType<{ size?: number; className?: string }>;
        iconColor: string;
    };
    const formatButtons: FormatButton[] = [
        { format: 'docx', labelKey: 'workstation.messageExport.exportAsWord', icon: Outlined.FileWord, iconColor: 'text-[#2F6CF6]' },
        { format: 'pdf', labelKey: 'workstation.messageExport.exportAsPdf', icon: Outlined.FilePdf, iconColor: 'text-[#E84B3C]' },
        { format: 'md', labelKey: 'workstation.messageExport.exportAsMarkdown', icon: Outlined.FileEditing, iconColor: 'text-[#F58A1F]' },
        { format: 'txt', labelKey: 'workstation.messageExport.exportAsTxt', icon: Outlined.FileTxt, iconColor: 'text-[#5C6680]' },
    ];

    return (
        <div
            role="toolbar"
            aria-label={localize('workstation.messageExport.entry')}
            className={cn(
                // In-place card that replaces the chat input while selection is active.
                'w-full rounded-xl border border-border bg-background shadow-lg',
                'flex flex-wrap items-center gap-1.5 pl-[10px] pr-4 py-2',
                isMobile && 'gap-1.5 pr-3',
            )}
        >
            {/* select all toggle — bidirectional: unticking clears the
                global flag AND any explicit picks (per user feedback "全选
                之后不能取消"). Same shadcn Checkbox as the per-message
                checkbox so they line up visually. */}
            <label
                className="flex shrink-0 cursor-pointer items-center gap-2 text-sm"
                title={localize('workstation.messageExport.selectAll')}
            >
                <Checkbox
                    checked={selectAllChecked}
                    onCheckedChange={(v) => setGlobalSelectAll(v === true)}
                />
                <span className="hidden min-[400px]:inline">{localize('workstation.messageExport.selectAll')}</span>
            </label>

            {/* spacer pushes action buttons to the right */}
            <div className="flex-1" />

            {/* action buttons — text labels collapse to icons below `lg`. */}
            {isMobile ? (
                <Button
                    variant="outline"
                    size="sm"
                    onClick={onExportToLocal}
                    className="h-7 gap-1 px-2 text-xs"
                    title={localize('workstation.messageExport.exportToLocal')}
                    aria-label={localize('workstation.messageExport.exportToLocal')}
                >
                    <Download className="h-3.5 w-3.5" />
                    <span className="hidden min-[400px]:inline">
                        {localize('workstation.messageExport.exportToLocal')}
                    </span>
                </Button>
            ) : (
                formatButtons.map(({ format, labelKey, icon: Icon, iconColor }) => (
                    <Button
                        key={format}
                        variant="outline"
                        size="sm"
                        disabled={exporting !== null}
                        onClick={() => handleExport(format)}
                        className="h-7 gap-1 px-2 text-xs"
                        title={localize(labelKey)}
                        aria-label={localize(labelKey)}
                    >
                        <Icon size={14} className={iconColor} />
                        <span className="hidden min-[400px]:inline">{localize(labelKey)}</span>
                    </Button>
                ))
            )}

            <Button
                variant="default"
                size="sm"
                onClick={handleImport}
                className="h-7 gap-1 px-2 text-xs"
                title={localize('workstation.messageExport.importToKnowledge')}
                aria-label={localize('workstation.messageExport.importToKnowledge')}
            >
                <Outlined.AddToKnowledgeBase size={14} />
                <span className="hidden min-[400px]:inline">
                    {localize('workstation.messageExport.importToKnowledge')}
                </span>
            </Button>

            <button
                type="button"
                onClick={exitSelectionMode}
                aria-label={localize('workstation.messageExport.cancel')}
                className="ml-1 inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            >
                <X className="h-3.5 w-3.5" />
            </button>
        </div>
    );
}
