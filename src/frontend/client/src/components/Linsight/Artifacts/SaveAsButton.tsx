/**
 * F035 Track H (P4): the artifact hand-off action. Markdown files expand into a
 * small menu (original md / pdf / docx via the backend convert endpoint); every
 * other type downloads the original file directly — so the label is honest per
 * type: "另存为" when there is a format choice, "下载" when there isn't.
 *
 * Two placements share the logic (`variant`):
 *   - 'rail'    the fixed trailing gutter of a file row (result card, workspace
 *               list). Reserved width, so the glyph never shifts the file name
 *               on hover, and a resting grey rather than hover-only visibility —
 *               a download you can't see until you hover is a download nobody
 *               finds, which is exactly how HTML reports ended up with no
 *               download entry at all (they open in a tab, never in the preview).
 *   - 'toolbar' preview-panel toolbar icon button.
 */
import { Outlined } from 'bisheng-icons';
import { useState } from 'react';
import { getMdDownload } from '~/api/linsight';
import { NotificationSeverity } from '~/common';
import FileIcon from '~/components/ui/icon/File';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '~/components/ui';
import { useLocalize } from '~/hooks';
import { useToastContext } from '~/Providers';
import { cn } from '~/utils';
import {
    type ArtifactFile,
    downloadArtifactFile,
    getFileExtension,
    saveConvertedBlob,
} from './artifactUtils';

type SaveAsVariant = 'rail' | 'toolbar';

interface SaveAsButtonProps {
    file: ArtifactFile;
    versionId: string;
    /** Trigger placement — see the file header. Defaults to the row rail. */
    variant?: SaveAsVariant;
    className?: string;
}

const TRIGGER_BASE =
    'flex shrink-0 items-center justify-center transition-colors focus-visible:outline-none ' +
    'focus-visible:ring-2 focus-visible:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-50';

const TRIGGER_VARIANT: Record<SaveAsVariant, string> = {
    // Three resting states, so the action reads as available without competing
    // with the file name (which turns brand-blue on row hover):
    //   at rest → faint grey · row hover → grey · own hover → brand + tint.
    // `hover:!text-blue-500` is deliberate: the row-hover and self-hover rules are
    // both :hover-based utilities on this element, so equal specificity makes CSS
    // source order the tiebreaker — `!` pins the winner instead of hoping.
    rail: 'size-6 rounded-md text-[#C0C4CC] group-hover/row:text-[#8C8C8C] hover:bg-blue-500/[0.07] hover:!text-blue-500',
    toolbar: 'size-7 rounded-lg text-[#8C8C8C] hover:bg-gray-100 hover:text-blue-500',
};

/** Parse a JSON error blob returned by the convert endpoint (if any). */
async function readBlobError(blob: Blob): Promise<string | null> {
    if (!(blob instanceof Blob) || !blob.type.includes('application/json')) return null;
    try {
        const data = JSON.parse(await blob.text());
        if (data.status_code && data.status_code !== 200) {
            return data.status_message || 'export failed';
        }
    } catch {
        /* not an error payload */
    }
    return null;
}

export function SaveAsButton({ file, versionId, variant = 'rail', className }: SaveAsButtonProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [busy, setBusy] = useState(false);

    // Markdown is the only type with a format choice (md / pdf / docx).
    const isMarkdown = getFileExtension(file.file_name) === 'md';
    const label = isMarkdown ? localize('com_linsight_save_as') : localize('com_ui_download');

    const handleDownloadOriginal = async () => {
        if (busy) return;
        setBusy(true);
        try {
            await downloadArtifactFile(file, versionId);
        } catch (e) {
            console.error('artifact download failed:', e);
            showToast?.({ message: localize('com_linsight_download_failed'), severity: NotificationSeverity.ERROR });
        } finally {
            setBusy(false);
        }
    };

    const handleExport = async (toType: 'pdf' | 'docx') => {
        if (busy) return;
        setBusy(true);
        showToast?.({ message: localize('com_linsight_exporting'), severity: NotificationSeverity.SUCCESS });
        try {
            const res = await getMdDownload({ file_url: file.file_url, file_name: file.file_name }, toType);
            const errMsg = res instanceof Blob ? await readBlobError(res) : null;
            if (errMsg) throw new Error(errMsg);
            const mime =
                toType === 'pdf'
                    ? 'application/pdf'
                    : 'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
            const blob = res instanceof Blob ? res : new Blob([res], { type: mime });
            saveConvertedBlob(blob, file.file_name, toType);
            showToast?.({ message: localize('com_linsight_export_success'), severity: NotificationSeverity.SUCCESS });
        } catch (e) {
            console.error(`${toType} export failed:`, e);
            showToast?.({ message: localize('com_linsight_export_failed'), severity: NotificationSeverity.ERROR });
        } finally {
            setBusy(false);
        }
    };

    const trigger = (
        <button
            type="button"
            disabled={busy}
            title={label}
            aria-label={label}
            className={cn(TRIGGER_BASE, TRIGGER_VARIANT[variant], className)}
            // File rows are themselves clickable (row click = preview) and answer
            // Enter, so the action must not bubble — otherwise downloading a file
            // would also open it.
            onClick={(e) => {
                e.stopPropagation();
                if (!isMarkdown) {
                    handleDownloadOriginal();
                }
            }}
            onKeyDown={(e) => e.stopPropagation()}
        >
            {busy ? (
                <Outlined.Loading className="size-4 animate-spin" />
            ) : (
                <Outlined.Download className="size-4" />
            )}
        </button>
    );

    if (!isMarkdown) {
        return trigger;
    }

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-[140px]">
                <DropdownMenuItem className="gap-2" onClick={handleDownloadOriginal}>
                    <FileIcon type="md" className="size-4" /> Markdown
                </DropdownMenuItem>
                <DropdownMenuItem className="gap-2" onClick={() => handleExport('pdf')}>
                    <FileIcon type="pdf" className="size-4" /> PDF
                </DropdownMenuItem>
                <DropdownMenuItem className="gap-2" onClick={() => handleExport('docx')}>
                    <FileIcon type="docx" className="size-4" /> Docx
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
