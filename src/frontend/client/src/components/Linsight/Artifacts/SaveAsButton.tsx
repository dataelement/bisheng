/**
 * F035 Track H (P4): the artifact hand-off action. Markdown files expand into a
 * small menu (original md / pdf / docx via the backend convert endpoint); every
 * other type downloads the original file directly — so the label is honest per
 * type: "另存为" when there is a format choice, "下载" when there isn't.
 *
 * Three placements share the logic (`variant`):
 *   - 'row'     sits directly after the file name in a list, revealed on row
 *               hover. Adjacency is the point: parked in a far-right gutter the
 *               glyph ended up ~1000px from a short file name, and the eye had
 *               to cross an empty row to work out which file it acted on.
 *               Hover-reveal is what keeps a column of ten identical glyphs from
 *               reading as noise — repetition is the noise, not the glyph.
 *   - 'inline'  always visible, for a SINGLE action inside a sentence (the
 *               one-deliverable result row). One instance isn't a column, so
 *               there is nothing to quiet down, and hiding the only download
 *               entry a run has is the failure this whole feature fixed.
 *   - 'toolbar' preview-panel toolbar icon button.
 *
 * 'row' hides with OPACITY, never `hidden`/`invisible`: the button keeps its
 * box, so revealing it can't re-truncate the file name next to it. Three
 * exceptions keep it from being a desktop-mouse-only affordance —
 * `focus-visible` (never focus something invisible), `data-[state=open]` (the
 * markdown menu must not fade out from under itself when the pointer leaves the
 * row), and `(hover: none)`, where the whole gesture doesn't exist and the
 * button simply stays put.
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

type SaveAsVariant = 'row' | 'inline' | 'toolbar';

interface SaveAsButtonProps {
    file: ArtifactFile;
    versionId: string;
    /** Trigger placement — see the file header. Defaults to the list-row action. */
    variant?: SaveAsVariant;
    className?: string;
}

const TRIGGER_BASE =
    'flex shrink-0 items-center justify-center transition-colors focus-visible:outline-none ' +
    'focus-visible:ring-2 focus-visible:ring-blue-500/40 disabled:cursor-not-allowed disabled:opacity-50';

// Shared by 'row' and 'inline': a quiet grey that turns brand on its own hover.
// One resting grey, not the two-step the far-right gutter needed — by the time
// a 'row' glyph is visible the row is already hovered, so there is no earlier
// state left to distinguish.
const ROW_GLYPH = 'size-6 rounded-md text-[#8C8C8C] hover:bg-blue-500/[0.07] hover:text-blue-500';

// Reveal rules for the list-row variant. `transition-opacity` (not the base
// `transition-colors`) so the fade is what animates.
const ROW_REVEAL =
    'opacity-0 transition-opacity group-hover/row:opacity-100 focus-visible:opacity-100 ' +
    'data-[state=open]:opacity-100 [@media(hover:none)]:!opacity-100';

const TRIGGER_VARIANT: Record<SaveAsVariant, string> = {
    row: `${ROW_GLYPH} ${ROW_REVEAL}`,
    inline: ROW_GLYPH,
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

export function SaveAsButton({ file, versionId, variant = 'row', className }: SaveAsButtonProps) {
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
