import { message } from "@/components/bs-ui/toast/use-toast";
import { locationContext } from "@/contexts/locationContext";
import { UploadIcon } from "lucide-react";
import { useContext } from "react";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";

export default function DropZone({ onDrop }) {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)

    // 1. 定义支持的文件格式（用于显示提示文本，不用于过滤）
    const supportedFormats = appConfig.enableEtl4lm 
        ? ['.PDF', '.TXT', '.DOCX', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV', '.DOC', '.PNG', '.JPG', '.JPEG', '.BMP']
        : ['.PDF', '.TXT', '.DOCX', '.DOC', '.PPT', '.PPTX', '.MD', '.HTML', '.XLS', '.XLSX', '.CSV'];
        const allowedExts = new Set(
            supportedFormats.map(ext => ext.toLowerCase().replace('.', ''))
        );
    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        // 2. 关闭默认过滤：accept设为null，允许所有文件进入onDrop
        accept: null,
        useFsAccessApi: false,
        onDrop: (acceptedFiles) => {
            // 1. 过滤不符合格式的文件
            const validFiles = acceptedFiles.filter(file => {
                // 获取文件后缀（无后缀则视为无效）
                const ext = file.name.split('.').pop()?.toLowerCase();
                return ext ? allowedExts.has(ext) : false;
            });

            // 2. 计算无效文件并提示
            const invalidFiles = acceptedFiles.filter(
                file => !validFiles.includes(file)
            );

            if (invalidFiles.length > 0) {
                message({
                    title: t('prompt'),
                    description: `不支持文件类型:${invalidFiles.map(f => f.name)}`,
                    variant: 'error'
                });
            }

            // 3. 只传递有效文件给父组件
            if (validFiles.length > 0) {
                onDrop(validFiles);
            }
        }
    });

    const formatText = appConfig.enableEtl4lm
        ? `支持的文件格式为  pdf（含扫描件）、txt、docx、ppt、pptx、md、html、xls、xlsx、csv、doc、png、jpg、jpeg、bmp；每个文件最大支持${appConfig.uploadFileMaxSize}mb；pdf支持溯源定位。`
        : `支持的文件格式为 pdf、txt、docx、doc、ppt、pptx、md、html、xls、xlsx、csv，每个文件最大支持${appConfig.uploadFileMaxSize}mb`

    return (
        <div {...getRootProps()} className="group h-48 border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary">
            <input {...getInputProps()} />
            <UploadIcon className="group-hover:text-primary size-5" />
            <p className="text-sm">{t('code.clickOrDragHere')}</p>
            <p className="bisheng-label px-4 text-center">{formatText}</p>
        </div>
    );
};