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
                ['.PDF', '.TXT', '.DOCX', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', '.DOC', '.PNG', '.JPG', '.JPEG', '.BMP']
                : ['.PDF', '.TXT', '.DOCX', '.DOC', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV']
        },
        useFsAccessApi: false,
        onDrop
    });

    const formatText = appConfig.enableEtl4lm
        ? `支持的文件格式为  pdf（含扫描件）、txt、docx、ppt、pptx、md、html、xls、xlsx、csv、doc、png、jpg、jpeg、bmp；每个文件最大支持${appConfig.uploadFileMaxSize}mb；pdf支持溯源定位。`
        : `支持的文件格式为 pdf、txt、docx、doc、ppt、pptx、md、html、xls、xlsx、csv，每个文件最大支持${appConfig.uploadFileMaxSize}mb`

    return <div {...getRootProps()} className="group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
        <input {...getInputProps()} />
        <UploadIcon className="group-hover:text-primary size-5" />
        <p className="text-sm">{t('code.clickOrDragHere')}</p>
        <p className="bisheng-label px-4 text-center">{formatText}</p>
    </div>
};
