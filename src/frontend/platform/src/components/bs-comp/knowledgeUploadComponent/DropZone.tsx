import { toast } from '@bisheng/ui';

import { locationContext } from "@/contexts/locationContext";
import { Outlined } from "bisheng-icons";
import { useContext } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";

const XIN_CHUANG_FORMATS = ['.WPS', '.ET', '.DPS'];
const MEDIA_FORMATS = ['.MP3', '.WAV', '.M4A', '.AAC', '.FLAC', '.OGG', '.MP4', '.MOV', '.AVI', '.MKV', '.WEBM'];

export function getKnowledgeUploadFormats(
    enableEtl4lm: boolean,
    mediaEnabled = false
): string[] {
    const enabledMediaFormats = mediaEnabled ? MEDIA_FORMATS : [];
    return enableEtl4lm
        ? ['.PDF', '.OFD', '.TXT', '.DOCX', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', '.DOC', '.PNG', '.JPG', '.JPEG', '.BMP', ...XIN_CHUANG_FORMATS, ...enabledMediaFormats]
        : ['.PDF', '.OFD', '.TXT', '.DOCX', '.DOC', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', ...XIN_CHUANG_FORMATS, ...enabledMediaFormats];
}

export function getKnowledgeUploadAccept(
    supportedFormats: string[],
    mediaEnabled = false
): Record<string, string[]> {
    return {
        'application/*': supportedFormats,
        'text/*': supportedFormats,
        'image/*': supportedFormats,
        ...(mediaEnabled
            ? {
                'audio/*': supportedFormats,
                'video/*': supportedFormats,
            }
            : {}),
    };
}

interface DropZoneProps {
    onDrop: (files: File[]) => void;
    compact?: boolean;
}

export default function DropZone({ onDrop, compact = false }: DropZoneProps) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    const mediaEnabled = !!appConfig.enableMediaUpload;

    const supportedFormats = getKnowledgeUploadFormats(appConfig.enableEtl4lm, mediaEnabled);
    const allowedExts = new Set(
        supportedFormats.map(ext => ext.toLowerCase().replace('.', ''))
    );
    const { getRootProps, getInputProps } = useDropzone({
        accept: getKnowledgeUploadAccept(supportedFormats, mediaEnabled),
        useFsAccessApi: false,
        onDrop: (acceptedFiles, disAcceptedFiles) => {
            // Filter files that don't match the allowed formats
            const validFiles = acceptedFiles.filter(file => {
                // Get file extension (if no extension, consider invalid)
                const ext = file.name.split('.').pop()?.toLowerCase();
                return ext ? allowedExts.has(ext) : false;
            });

            if (disAcceptedFiles.length > 0) {
                // @ts-ignore
                const uniqueExtensions = [...new Set(
                    disAcceptedFiles
                        .map(f => f.file.name.split('.').pop()?.toLowerCase())
                        .filter(Boolean)
                )];
                toast.show({ type: 'error', message: [String(t('prompt') ?? ''), String(t('unsupportedFileType', { extensions: uniqueExtensions.join(', ') }) ?? '')].filter(Boolean).join('\n') });
            }

            // Only pass valid files to parent component
            if (validFiles.length > 0) {
                onDrop(validFiles);
            }
        }
    });

    const mediaMaxSize = appConfig.uploadMediaMaxSize ?? 1024;
    const formatKey = appConfig.enableEtl4lm
        ? (mediaEnabled ? 'supportedFormatsWithImages' : 'supportedFormatsWithImagesWithoutMedia')
        : (mediaEnabled ? 'supportedFormatsWithoutImages' : 'supportedFormatsWithoutImagesWithoutMedia');
    const formatText = t(formatKey, { maxSize: appConfig.uploadFileMaxSize ?? 50, mediaMaxSize });

    return (
      <>
        <div {...getRootProps()} className={compact
            ? "group flex min-h-36 cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border-deep bg-fill-1 px-6 py-5 text-center transition-colors hover:border-blue-500 hover:bg-blue-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
            : "group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary"}>
            <input {...getInputProps()} />
            <Outlined.Upload className={compact ? "size-8 text-blue-500" : "group-hover:text-primary size-5"} aria-hidden="true" />
            <p className="text-body text-text-1">{t('code.clickOrDragHere')}</p>
            <p className={compact ? "text-caption text-text-3" : "bisheng-label px-4 text-center"}>
                {compact ? t(mediaEnabled ? 'f118.upload_limits_media' : 'f118.upload_limits', {
                    ns: 'knowledge', maxSize: appConfig.uploadFileMaxSize ?? 50, mediaMaxSize,
                }) : formatText}
            </p>
        </div>
        {compact && (
            <details className="text-caption text-text-3">
                <summary className="cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40">{t('f118.upload_formats', { ns: 'knowledge' })}</summary>
                <p className="mt-2 max-w-4xl break-words leading-5">{formatText}</p>
            </details>
        )}
      </>
    );
};
