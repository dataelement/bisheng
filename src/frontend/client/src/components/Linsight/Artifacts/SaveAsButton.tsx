/**
 * F035 Track H (P4): the artifact hand-off action. Every type opens a menu now —
 * Markdown offers three local formats (original md / pdf / docx via the backend
 * convert endpoint), other types a single "download to local" — followed, after a
 * separator, by "save into knowledge space".
 *
 * The separator is load-bearing: the items above it end at the user's disk, the
 * one below writes into a shared knowledge space, which is a different kind of
 * commitment and must not sit flush against a download.
 *
 * A share-link viewer never gets the knowledge-space item: they are neither the
 * task owner nor necessarily logged in, so the uploadable-space lookup behind it
 * doesn't apply to them. With nothing left to choose, a non-Markdown artifact
 * falls back to the plain one-click download button rather than a one-item menu.
 *
 * Three placements share the logic (`variant`):
 *   - 'labeled' the file-list row action (design node 12221-40681): always
 *               visible, icon + "另存为" text, right-aligned in the row. A
 *               WORDED action doesn't read as noise when repeated down a list
 *               the way a bare glyph did — the label is what tells a
 *               first-time user the hand-off exists, so it must not hide
 *               behind a hover. Used by the delivery card, the workspace
 *               panel, and the workspace drawer.
 *   - 'inline'  icon-only, for a SINGLE action inside a sentence (the
 *               one-deliverable result row) where a worded button would
 *               interrupt the copy.
 *   - 'toolbar' preview-panel toolbar icon button.
 */
import { Outlined } from 'bisheng-icons';
import { useRef, useState } from 'react';
import { getMdDownload } from '~/api/linsight';
import { listUploadableSpacesApi } from '~/api/messageExport';
import { NotificationSeverity } from '~/common';
import { ActionMenuContent, ActionMenuDivider, ActionMenuItem } from '~/components/ActionMenu';
import { DropdownMenu, DropdownMenuTrigger } from '~/components/ui';
import { useLocalize } from '~/hooks';
import { AddToKnowledgeModal } from '~/pages/Subscription/Article/AddToKnowledgeModal';
import { useToastContext } from '~/Providers';
import { cn } from '~/utils';
import { getShareTokenFromPath } from '~/utils/shareToken';
import {
    type ArtifactFile,
    downloadArtifactFile,
    getFileExtension,
    saveConvertedBlob,
} from './artifactUtils';
import { useSaveArtifactToKnowledge } from './useSaveArtifactToKnowledge';

type SaveAsVariant = 'labeled' | 'inline' | 'toolbar';

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

const TRIGGER_VARIANT: Record<SaveAsVariant, string> = {
    // Design 12221-40681: 14px glyph + 12px label, 8px/2px padding, 8px radius.
    // No hover background — the pointer is answered by the text itself going
    // from a resting grey to near-black, so the button never stacks a second
    // fill on top of the row's own hover grey.
    labeled: 'gap-1 rounded-lg px-2 py-0.5 text-xs leading-5 text-[#8C8C8C] hover:text-[#212121]',
    // A quiet grey glyph that turns brand on its own hover — color only, no
    // hover fill (same rule as 'labeled').
    inline: 'size-6 rounded-md text-[#8C8C8C] hover:text-blue-500',
    toolbar: 'size-7 rounded-lg text-[#8C8C8C] hover:bg-gray-100 hover:text-blue-500',
};

// Glyph size per placement: 14px beside the "另存为" label and for the bare
// action tucked into a sentence, 16px in the preview toolbar.
const GLYPH_SIZE: Record<SaveAsVariant, string> = {
    labeled: 'size-3.5',
    inline: 'size-3.5',
    toolbar: 'size-4',
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

export function SaveAsButton({ file, versionId, variant = 'labeled', className }: SaveAsButtonProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [busy, setBusy] = useState(false);
    /** Was the menu opened by pointer? Drives whether closing restores focus. */
    const pointerOpened = useRef(false);
    const { pickerOpen, setPickerOpen, openPicker, saveTo, saving } =
        useSaveArtifactToKnowledge(file, versionId);

    // Markdown is the only type with a local format choice (md / pdf / docx).
    const isMarkdown = getFileExtension(file.file_name) === 'md';
    const canSaveToKnowledge = !getShareTokenFromPath();
    const hasMenu = isMarkdown || canSaveToKnowledge;
    const label = hasMenu ? localize('com_linsight_save_as') : localize('com_ui_download');

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

    // The trigger leads with the glyph for what it actually does: "save as"
    // wherever it opens the format/destination menu, a plain download arrow for
    // the share-viewer fallback, which only ever downloads the file as-is.
    const glyphSize = GLYPH_SIZE[variant];
    const glyph =
        busy || saving ? (
            <Outlined.Loading className={cn(glyphSize, 'animate-spin')} />
        ) : hasMenu ? (
            <Outlined.FileSaveAs className={glyphSize} />
        ) : (
            <Outlined.Download className={glyphSize} />
        );

    const trigger = (
        <button
            type="button"
            disabled={busy || saving}
            title={label}
            aria-label={label}
            className={cn(TRIGGER_BASE, TRIGGER_VARIANT[variant], className)}
            // Pointer opens must not leave a focus ring behind: Radix hands
            // focus back to the trigger when the menu closes, and Chrome
            // re-applies :focus-visible to that programmatic focus. Remember
            // how the menu was opened so the close can skip the hand-back.
            onPointerDown={() => {
                pointerOpened.current = true;
            }}
            // File rows are themselves clickable (row click = preview) and answer
            // Enter, so the action must not bubble — otherwise downloading a file
            // would also open it.
            onClick={(e) => {
                e.stopPropagation();
                if (!hasMenu) {
                    handleDownloadOriginal();
                }
            }}
            onKeyDown={(e) => {
                // A keyboard open DOES want the focus hand-back on close —
                // otherwise the tab position is lost with nothing to show for it.
                pointerOpened.current = false;
                e.stopPropagation();
            }}
        >
            {glyph}
            {variant === 'labeled' && <span className="whitespace-nowrap">{label}</span>}
        </button>
    );

    if (!hasMenu) {
        return trigger;
    }

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
                {/* Shared ActionMenu chrome — same panel as the sidebar convo menu
                    (12px radius, soft shadow, 32px rows, grey 16px leading icons).
                    File-type glyphs follow getFileTypeIcon's md/pdf/docx mapping. */}
                {/* w-auto: the longest label ("Save to knowledge space" in en)
                    overflows the frame's fixed 160px — let content set the width. */}
                <ActionMenuContent
                    className="w-auto min-w-[160px]"
                    onClick={(e) => e.stopPropagation()}
                    // Mouse users get no focus hand-back, so the trigger can't
                    // sit there wearing a focus ring after the menu is gone.
                    onCloseAutoFocus={(e) => {
                        if (pointerOpened.current) e.preventDefault();
                    }}
                >
                    {isMarkdown ? (
                        <>
                            <ActionMenuItem
                                icon={<Outlined.FileEditing />}
                                label={localize('com_linsight.downloadAs', { format: 'Markdown' })}
                                onClick={handleDownloadOriginal}
                            />
                            <ActionMenuItem
                                icon={<Outlined.FilePdf />}
                                label={localize('com_linsight.downloadAs', { format: 'PDF' })}
                                onClick={() => handleExport('pdf')}
                            />
                            <ActionMenuItem
                                icon={<Outlined.FileWord />}
                                label={localize('com_linsight.downloadAs', { format: 'Docx' })}
                                onClick={() => handleExport('docx')}
                            />
                        </>
                    ) : (
                        <ActionMenuItem
                            icon={<Outlined.Download />}
                            label={localize('com_linsight.downloadToLocal')}
                            onClick={handleDownloadOriginal}
                        />
                    )}
                    {canSaveToKnowledge && (
                        <>
                            <ActionMenuDivider />
                            <ActionMenuItem
                                icon={<Outlined.AddToKnowledgeBase />}
                                label={localize('com_linsight.saveToKnowledge')}
                                disabled={saving}
                                onClick={openPicker}
                            />
                        </>
                    )}
                </ActionMenuContent>
            </DropdownMenu>
            {/* Sibling of the menu, not a child: inside DropdownMenuContent it
                would unmount the moment the menu closes on item select. */}
            {canSaveToKnowledge && (
                <AddToKnowledgeModal
                    open={pickerOpen}
                    onOpenChange={setPickerOpen}
                    mode="channel_sync"
                    dataSourceApi={listUploadableSpacesApi}
                    onSyncSelect={saveTo}
                />
            )}
        </>
    );
}
