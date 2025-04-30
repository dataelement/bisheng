// 上传文件组件
import { UploadIcon } from "@/components/bs-icons";
import { useDropzone } from "react-dropzone";
import { useTranslation } from "react-i18next";
import { useToast } from "../toast/use-toast";
import { cname } from "../utils";
import axios from "@/controllers/request";

// 目前只支持上传单个文件
export default function SimpleUpload({ filekey, uploadUrl, accept, className = '', onUpload, onProgress, onError, onSuccess, preCheck = null }) {
    const { t } = useTranslation();
    const { toast } = useToast()

    const onDrop = async (acceptedFiles) => {
        const sizeLimit = 50 * 1024 * 1024;
        const errorFile = [];
        const files = []
        acceptedFiles.forEach(file => {
            file.size < sizeLimit ?
                files.push(file) :
                errorFile.push(file.name);
        });
        errorFile.length && toast({
            title: t('prompt'),
            description: errorFile.map(str => `${t('code.file')}: ${str} ${t('code.sizeExceedsLimit')}`),
        });
        if (!files.length) return

         // 执行预校验（如果提供了preCheck函数）
         if (preCheck) {
            try {
                const checkResult = await preCheck(files[0]);
                if (checkResult?.valid === false) {
                    toast({
                        title: t('prompt'),
                        description: checkResult.message || t('code.preCheckFailed'),
                    });
                    return;
                }
            } catch (error) {
                toast({
                    title: t('prompt'),
                    description: error.message || t('code.preCheckError'),
                });
                return;
            }
        }

        const formData = new FormData();
        formData.append(filekey, files[0]);

        const res = await axios.post(uploadUrl, formData);
        onSuccess(files[0].name, res.file_path)
    }

    // 将文件扩展名转换为对应的MIME类型
    const getMimeType = (ext) => {
        const mimeTypes = {
            // 文档
            pdf: 'application/pdf',
            json: 'application/json',
            xml: 'application/xml',
            doc: 'application/msword',
            docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            // 图片
            jpg: 'image/jpeg',
            jpeg: 'image/jpeg',
            png: 'image/png',
            gif: 'image/gif',
            webp: 'image/webp',
            svg: 'image/svg+xml',
            // 表格
            xls: 'application/vnd.ms-excel',
            xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            csv: 'text/csv',
            // 压缩文件
            zip: 'application/zip',
            rar: 'application/x-rar-compressed',
            '7z': 'application/x-7z-compressed',
            // 文本
            txt: 'text/plain',
            md: 'text/markdown',
            html: 'text/html',
            // 其他
            mp3: 'audio/mpeg',
            mp4: 'video/mp4',
            mov: 'video/quicktime'
        };
        
        return mimeTypes[ext.toLowerCase()] || 'application/*';
    };

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        accept: accept.reduce((acc, ext) => {
            const mimeType = getMimeType(ext);
            if (!acc[mimeType]) {
                acc[mimeType] = [];
            }
            acc[mimeType].push(`.${ext}`);
            return acc;
        }, {}),
        multiple: false,
        useFsAccessApi: false,
        onDrop
    });


    return <div {...getRootProps()} className={cname('group h-[100px] border border-dashed rounded-md flex flex-col justify-center items-center cursor-pointer gap-3 hover:border-primary', className)}>
        <input {...getInputProps()} />
        <UploadIcon className="group-hover:text-primary" />
        {isDragActive ? <p className="text-gray-400 text-sm">{t('code.dropFileHere')}</p> : <p className="text-gray-400 text-sm">{t('code.clickOrDragHere')}</p>}
    </div>
};
