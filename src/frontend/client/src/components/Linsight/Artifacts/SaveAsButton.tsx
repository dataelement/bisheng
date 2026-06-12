/**
 * F035 Track H (P4): "save as" action for an artifact file. Markdown files
 * expand into a small menu (original md / pdf / docx via the backend convert
 * endpoint); every other type downloads the original file directly.
 */
import { Download } from 'lucide-react';
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
import {
    type ArtifactFile,
    downloadArtifactFile,
    getFileExtension,
    saveConvertedBlob,
} from './artifactUtils';

interface SaveAsButtonProps {
    file: ArtifactFile;
    versionId: string;
    /** icon-only style for the preview panel toolbar; default is the text link */
    iconOnly?: boolean;
}

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

export function SaveAsButton({ file, versionId, iconOnly = false }: SaveAsButtonProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const [busy, setBusy] = useState(false);

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

    const trigger = iconOnly ? (
        <button
            type="button"
            disabled={busy}
            aria-label={localize('com_linsight_save_as')}
            className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 disabled:opacity-50"
        >
            <Download size={16} />
        </button>
    ) : (
        <button
            type="button"
            disabled={busy}
            className="shrink-0 whitespace-nowrap text-xs text-gray-500 hover:text-blue-600 disabled:opacity-50"
        >
            {localize('com_linsight_save_as')}
        </button>
    );

    // markdown: choose original / pdf / docx
    if (getFileExtension(file.file_name) === 'md') {
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

    // other types: direct download
    return (
        <span onClick={handleDownloadOriginal} role="presentation">
            {trigger}
        </span>
    );
}
