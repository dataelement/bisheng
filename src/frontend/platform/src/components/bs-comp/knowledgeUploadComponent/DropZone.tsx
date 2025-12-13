import { message } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { UploadIcon } from "lucide-react";
import { useContext } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";

export default function DropZone({ onDrop }) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    // Define supported file formats (for display purposes only, not for filtering)
    const supportedFormats = appConfig.enableEtl4lm
        ? ['.PDF', '.TXT', '.DOCX', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', '.DOC', '.PNG', '.JPG', '.JPEG', '.BMP']
        : ['.PDF', '.TXT', '.DOCX', '.DOC', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV'];
    const allowedExts = new Set(
        supportedFormats.map(ext => ext.toLowerCase().replace('.', ''))
    );
    const { getRootProps, getInputProps } = useDropzone({
        accept: {
            'application/*': supportedFormats
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

    const formatText = appConfig.enableEtl4lm
        ? t('supportedFormatsWithImages', { maxSize: appConfig.uploadFileMaxSize })
        : t('supportedFormatsWithoutImages', { maxSize: appConfig.uploadFileMaxSize })

    return (
        <div {...getRootProps()} className="group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
            <input {...getInputProps()} />
            <UploadIcon className="group-hover:text-primary size-5" />
            <p className="text-sm">{t('code.clickOrDragHere')}</p>
            <p className="bisheng-label px-4 text-center">{formatText}</p>
        </div>
    );
};