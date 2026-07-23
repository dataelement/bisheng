import { message } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { UploadIcon } from "lucide-react";
import { useContext } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { knowledgeUploadCapabilities } from "@/pages/KnowledgePage/knowledgeUploadCapabilities";

const XIN_CHUANG_FORMATS = ['.WPS', '.ET', '.DPS'];
const MEDIA_FORMATS = ['.MP3', '.WAV', '.M4A', '.AAC', '.FLAC', '.OGG', '.MP4', '.MOV', '.AVI', '.MKV', '.WEBM'];

export function getKnowledgeUploadFormats(
    enableEtl4lm: boolean,
    mediaEnabled: boolean = knowledgeUploadCapabilities.media
): string[] {
    const enabledMediaFormats = mediaEnabled ? MEDIA_FORMATS : [];
    return enableEtl4lm
        ? ['.PDF', '.OFD', '.TXT', '.DOCX', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', '.DOC', '.PNG', '.JPG', '.JPEG', '.BMP', ...XIN_CHUANG_FORMATS, ...enabledMediaFormats]
        : ['.PDF', '.OFD', '.TXT', '.DOCX', '.DOC', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', ...XIN_CHUANG_FORMATS, ...enabledMediaFormats];
}

export function getKnowledgeUploadAccept(
    supportedFormats: string[],
    mediaEnabled: boolean = knowledgeUploadCapabilities.media
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

export default function DropZone({ onDrop }) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    const supportedFormats = getKnowledgeUploadFormats(appConfig.enableEtl4lm);
    const allowedExts = new Set(
        supportedFormats.map(ext => ext.toLowerCase().replace('.', ''))
    );
    const { getRootProps, getInputProps } = useDropzone({
        accept: getKnowledgeUploadAccept(supportedFormats),
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
                message({
                    title: t('prompt'),
                    description: t('unsupportedFileType', { extensions: uniqueExtensions.join(', ') }),
                    variant: 'error'
                });
            }

            // Only pass valid files to parent component
            if (validFiles.length > 0) {
                onDrop(validFiles);
            }
        }
    });

    const mediaMaxSize = appConfig.uploadMediaMaxSize ?? 1024;
    const formatKey = appConfig.enableEtl4lm
        ? (knowledgeUploadCapabilities.media ? 'supportedFormatsWithImages' : 'supportedFormatsWithImagesWithoutMedia')
        : (knowledgeUploadCapabilities.media ? 'supportedFormatsWithoutImages' : 'supportedFormatsWithoutImagesWithoutMedia');
    const formatText = t(formatKey, { maxSize: appConfig.uploadFileMaxSize, mediaMaxSize });

    return (
        <div {...getRootProps()} className="group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
            <input {...getInputProps()} />
            <UploadIcon className="group-hover:text-primary size-5" />
            <p className="text-sm">{t('code.clickOrDragHere')}</p>
            <p className="bisheng-label px-4 text-center">{formatText}</p>
        </div>
    );
};
