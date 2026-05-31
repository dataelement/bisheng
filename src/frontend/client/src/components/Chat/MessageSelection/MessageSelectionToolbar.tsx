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

import { useCallback, useState } from 'react';
import { Download, FileText, FileType2, Library, X } from 'lucide-react';
import {
    type ExportFormat,
    exportMessagesApi,
    triggerBrowserDownload,
} from '~/api/messageExport';
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
        selectAll,
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
            } catch (err) {
                showToast({
                    message: localize('workstation.messageExport.renderFailed'),
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
    const formatButtons: Array<{ format: ExportFormat; labelKey: string; icon: typeof FileText }> = [
        { format: 'docx', labelKey: 'workstation.messageExport.exportAsWord', icon: FileText },
        { format: 'pdf', labelKey: 'workstation.messageExport.exportAsPdf', icon: FileText },
        { format: 'md', labelKey: 'workstation.messageExport.exportAsMarkdown', icon: FileType2 },
        { format: 'txt', labelKey: 'workstation.messageExport.exportAsTxt', icon: FileText },
    ];

    return (
        <div
            role="toolbar"
            aria-label={localize('workstation.messageExport.entry')}
            className={cn(
                'fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background shadow-lg',
                'flex items-center gap-2 px-4 py-3',
                isMobile && 'gap-3 px-3 py-2',
            )}
        >
            {/* select all toggle */}
            <label className="flex shrink-0 cursor-pointer items-center gap-2 text-sm">
                <Checkbox
                    checked={selectAllChecked}
                    onCheckedChange={(v) => {
                        if (v) selectAll();
                        // Note: unticking 全选 doesn't clear selection — user
                        // can still keep their explicit picks. To clear all,
                        // use the close button.
                    }}
                />
                <span>{localize('workstation.messageExport.selectAll')}</span>
            </label>

            {/* spacer pushes action buttons to the right */}
            <div className="flex-1" />

            {/* action buttons */}
            {isMobile ? (
                <Button
                    variant="outline"
                    size="sm"
                    onClick={onExportToLocal}
                    className="gap-1.5"
                >
                    <Download className="h-4 w-4" />
                    {localize('workstation.messageExport.exportToLocal')}
                </Button>
            ) : (
                formatButtons.map(({ format, labelKey, icon: Icon }) => (
                    <Button
                        key={format}
                        variant="outline"
                        size="sm"
                        disabled={exporting !== null}
                        onClick={() => handleExport(format)}
                        className="gap-1.5"
                    >
                        <Icon className="h-4 w-4" />
                        {localize(labelKey)}
                    </Button>
                ))
            )}

            <Button
                variant="default"
                size="sm"
                onClick={handleImport}
                className="gap-1.5"
            >
                <Library className="h-4 w-4" />
                {localize('workstation.messageExport.importToKnowledge')}
            </Button>

            <button
                type="button"
                onClick={exitSelectionMode}
                aria-label={localize('workstation.messageExport.cancel')}
                className="ml-1 inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
            >
                <X className="h-4 w-4" />
            </button>
        </div>
    );
}
