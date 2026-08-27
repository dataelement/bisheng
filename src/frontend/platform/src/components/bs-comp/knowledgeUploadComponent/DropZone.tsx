import { message } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { UploadIcon } from "lucide-react";
import { useContext } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";

interface DropZoneProps {
    onDrop: (files: File[]) => void;
}

const KNOWLEDGE_UPLOAD_FORMATS = [
    '.PDF', '.TXT', '.DOCX', '.DOC', '.PPT', '.PPTX', '.MD', '.HTML', '.HTM', '.XLS', '.XLSX',
];

export default function DropZone({ onDrop }: DropZoneProps) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    const allowedExts = new Set(
        KNOWLEDGE_UPLOAD_FORMATS.map(ext => ext.toLowerCase().replace('.', ''))
    );
    const { getRootProps, getInputProps } = useDropzone({
        accept: {
            'application/*': KNOWLEDGE_UPLOAD_FORMATS,
            'text/*': KNOWLEDGE_UPLOAD_FORMATS,
        },
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

    const formatText = t('supportedFormatsWithoutImages', { maxSize: appConfig.uploadFileMaxSize })

    return (
        <div {...getRootProps()} className="group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
            <input {...getInputProps()} />
            <UploadIcon className="group-hover:text-primary size-5" />
            <p className="text-sm">{t('code.clickOrDragHere')}</p>
            <p className="bisheng-label px-4 text-center">{formatText}</p>
        </div>
    );
};
