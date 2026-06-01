/**
 * F028 — H5 bottom sheet that lets the user pick an export file format.
 *
 * On PC the four format buttons sit inline in the toolbar; on H5 (viewport <
 * 768px) the toolbar shows a single "Export to local" button which opens
 * this sheet. The actual download is performed here so the parent only has
 * to track open/close and the message list.
 */

import { useCallback, useState, type ComponentType } from 'react';
import { Outlined } from 'bisheng-icons';
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

    type FormatOption = {
        format: ExportFormat;
        labelKey: string;
        icon: ComponentType<{ size?: number; className?: string }>;
        iconColor: string;
    };
    const options: FormatOption[] = [
        { format: 'docx', labelKey: 'workstation.messageExport.exportAsWord', icon: Outlined.FileWord, iconColor: 'text-[#2F6CF6]' },
        { format: 'pdf', labelKey: 'workstation.messageExport.exportAsPdf', icon: Outlined.FilePdf, iconColor: 'text-[#E84B3C]' },
        { format: 'md', labelKey: 'workstation.messageExport.exportAsMarkdown', icon: Outlined.FileEditing, iconColor: 'text-[#F58A1F]' },
        { format: 'txt', labelKey: 'workstation.messageExport.exportAsTxt', icon: Outlined.FileTxt, iconColor: 'text-[#5C6680]' },
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
            <SheetContent side="bottom" className="rounded-t-2xl px-4 pb-6 pt-3">
                <SheetHeader className="pb-2">
                    <SheetTitle className="text-center text-sm font-medium text-muted-foreground">
                        {localize('workstation.messageExport.selectExportFormat')}
                    </SheetTitle>
                </SheetHeader>
                <div className="flex flex-col gap-1.5">
                    {options.map(({ format, labelKey, icon: Icon, iconColor }) => (
                        <button
                            key={format}
                            type="button"
                            disabled={busy !== null}
                            onClick={() => handle(format)}
                            className={cn(
                                'flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm',
                                'hover:bg-muted active:bg-muted disabled:opacity-50',
                            )}
                        >
                            <Icon size={18} className={iconColor} />
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
