import { locationContext } from "@/contexts/locationContext";
import { UploadIcon } from "lucide-react";
import { useContext } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";

export default function DropZone({ onDrop }) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        accept: {
            'application/*': appConfig.enableEtl4lm ?
                ['.PDF', '.TXT', '.DOCX', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.DOC', '.PNG', '.JPG', '.JPEG', '.BMP']
                : ['.PDF', '.TXT', '.DOCX', '.DOC', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX']
        },
        useFsAccessApi: false,
        onDrop
    });

    const formatText = appConfig.enableEtl4lm
        ? 'pdf、txt、docx、pptx、md、html、png、jpg、jpeg、bmp'
        : 'pdf、txt、docx、doc、pptx、md、html'

    return <div {...getRootProps()} className="group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
        <input {...getInputProps()} />
        <UploadIcon className="group-hover:text-primary size-5" />
        <p className="text-sm">{t('code.clickOrDragHere')}</p>
        <p className="bisheng-label">支持的文件格式{formatText}，每个文件最大支持{appConfig.uploadFileMaxSize}mb</p>
    </div>
};
