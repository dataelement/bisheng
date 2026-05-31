/**
 * F028 — H5 bottom sheet that lets the user pick an export file format.
 *
 * On PC the four format buttons sit inline in the toolbar; on H5 (viewport <
 * 768px) the toolbar shows a single "Export to local" button which opens
 * this sheet. The actual download is performed here so the parent only has
 * to track open/close and the message list.
 */

import { useCallback, useState } from 'react';
import { FileText, FileType2 } from 'lucide-react';
import {
    type ExportFormat,
    exportMessagesApi,
    triggerBrowserDownload,
} from '~/api/messageExport';
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from '~/components/ui/Sheet';
import { useLocalize } from '~/hooks';
import { type SelectableMessage, useMessageSelection } from '~/hooks/useMessageSelection';
import { useToastContext } from '~/Providers';
import { NotificationSeverity } from '~/common';
import { cn } from '~/utils';

export interface ExportFormatSheetProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    chatId: string;
    messages: readonly SelectableMessage[];
}

function _toBackendIds(ids: string[]): number[] {
    const out: number[] = [];
    for (const raw of ids) {
        const n = Number.parseInt(raw, 10);
        if (Number.isFinite(n)) out.push(n);
    }
    return out;
}

export function ExportFormatSheet({
    open,
    onOpenChange,
    chatId,
    messages,
}: ExportFormatSheetProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const { getSelectedIds, isOverLimit } = useMessageSelection();
    const [busy, setBusy] = useState<ExportFormat | null>(null);

    const options: Array<{ format: ExportFormat; labelKey: string; icon: typeof FileText }> = [
        { format: 'docx', labelKey: 'workstation.messageExport.exportAsWord', icon: FileText },
        { format: 'pdf', labelKey: 'workstation.messageExport.exportAsPdf', icon: FileText },
        { format: 'md', labelKey: 'workstation.messageExport.exportAsMarkdown', icon: FileType2 },
        { format: 'txt', labelKey: 'workstation.messageExport.exportAsTxt', icon: FileText },
    ];

    const handle = useCallback(
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
            setBusy(format);
            try {
                const file = await exportMessagesApi({
                    chatId,
                    messageIds: _toBackendIds(ids),
                    format,
                });
                triggerBrowserDownload(file);
                onOpenChange(false);
            } catch {
                showToast({
                    message: localize('workstation.messageExport.renderFailed'),
                    severity: NotificationSeverity.ERROR,
                });
            } finally {
                setBusy(null);
            }
        },
        [chatId, messages, getSelectedIds, isOverLimit, showToast, localize, onOpenChange],
    );

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent side="bottom" className="rounded-t-xl">
                <SheetHeader>
                    <SheetTitle>{localize('workstation.messageExport.selectExportFormat')}</SheetTitle>
                </SheetHeader>
                <div className="flex flex-col">
                    {options.map(({ format, labelKey, icon: Icon }) => (
                        <button
                            key={format}
                            type="button"
                            disabled={busy !== null}
                            onClick={() => handle(format)}
                            className={cn(
                                'flex items-center gap-3 border-b border-border px-4 py-4 text-left text-base',
                                'hover:bg-muted disabled:opacity-50',
                            )}
                        >
                            <Icon className="h-5 w-5 text-muted-foreground" />
                            <span className="flex-1">{localize(labelKey)}</span>
                            {busy === format && (
                                <span className="text-xs text-muted-foreground">…</span>
                            )}
                        </button>
                    ))}
                </div>
            </SheetContent>
        </Sheet>
    );
}
