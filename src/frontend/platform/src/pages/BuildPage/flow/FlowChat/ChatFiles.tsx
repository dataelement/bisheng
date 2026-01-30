import { useToast } from "@/components/bs-ui/toast/use-toast";
import { generateUUID } from "@/components/bs-ui/utils";
import Loading from "@/components/ui/loading";
import { locationContext } from "@/contexts/locationContext";
import { uploadChatFile } from "@/controllers/API/flow";
import { getFileExtension } from "@/util/utils";
import { FileIcon, PaperclipIcon, X } from "lucide-react";
import { forwardRef, useContext, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const checkFileType = (file, accepts) => {
    if (!accepts || accepts === '*') return true;
    const fileName = file.name.toLowerCase();
    const acceptArr = accepts.split(',').map(a => a.trim().toLowerCase());

    // 检查后缀名 (例如 .pdf) 或 MIME type
    return acceptArr.some(type => {
        if (type.startsWith('.')) {
            return fileName.endsWith(type);
        }
        return file.type.match(new RegExp(type.replace('*', '.*')));
    });
};


// @accepts '.png,.jpg'
export default forwardRef(function ChatFiles({ v, accepts, disabled, onChange }, ref) {

    const { t } = useTranslation();
    const [files, setFiles] = useState([]);
    const filesRef = useRef([]);
    const remainingUploadsRef = useRef(0);
    const { appConfig } = useContext(locationContext);
    // const fileAccepts = useMemo(() => appConfig.libAccepts.map((ext) => `.${ext}`), [appConfig.libAccepts]);
    const { toast } = useToast();

    const fileInputRef = useRef(null);
    const fileSizeLimit = appConfig.uploadFileMaxSize * 1024 * 1024; // File size limit in bytes


    const handleFileChange = (selectedFiles) => {
        const validFiles = [];
        const invalidTips = []; // 仅存储无效文件的提示文案
        const invalidTypeFiles = [];

        fileInputRef.current.value = '';
        const allowedExtensions = accepts
            ? new Set(accepts.split(',').map(ext => ext.trim().toLowerCase().replace(/^\./, '')))
            : new Set();

        selectedFiles.forEach((file) => {
            // 1. 先校验文件类型
            if (!checkFileType(file, accepts)) {
                invalidTypeFiles.push(file);
            } else if (allowedExtensions.size > 0) {
                const fileExt = getFileExtension(file.name).toLowerCase();
                if (!allowedExtensions.has(fileExt)) {
                    invalidTips.push(t('chat.fileTypeNotAllowed', {
                        name: file.name,
                        type: fileExt
                    }));
                    return; // 类型不符合，跳过后续校验
                }
            }

            if (invalidTypeFiles.length > 0) {
                return toast({
                    variant: 'error',
                    description: t('com_ui_upload_file_type_error')
                }); // 请确保你有对应多语言key或直接写死中文测试
            }
            // 2. 再校验文件大小
            if (file.size > fileSizeLimit) {
                invalidTips.push(t('chat.fileExceedRemoved', { name: file.name, size: appConfig.uploadFileMaxSize }));
                return; // 大小不符合，跳过
            }

            // 3. 所有校验通过，加入有效文件列表
            validFiles.push({ id: generateUUID(6), file });
        });

        // 显示无效文件提示（区分类型/大小错误）
        if (invalidTips.length > 0) {
            toast({
                variant: 'info',
                description: invalidTips.join('；'),
            });
        }

        // 只要有有效文件就继续上传流程
        if (!validFiles.length) return;

        // 以下逻辑完全保留，无需修改
        onChange(null);
        const filesWithProgress = validFiles.map(({ file, id }) => {
            return {
                name: file.name,
                size: file.size,
                type: file.type,
                isUploading: true,
                progress: 0,
                id,
                file
            };
        });

        setFiles(prevFiles => {
            const res = [...prevFiles, ...filesWithProgress];
            filesRef.current = res;
            return res;
        });

        remainingUploadsRef.current = validFiles.length;

        const uploadPromises = validFiles.map(({ file, id }) => {
            return uploadChatFile(v, file, (progress) => {
                setFiles((prevFiles) => {
                    const updatedFiles = prevFiles.map(f => {
                        if (f.id === id) {
                            return { ...f, progress };
                        }
                        return f;
                    });
                    filesRef.current = updatedFiles;
                    return updatedFiles;
                });
            }).then(response => {
                const filePath = response.file_path;
                filesRef.current = filesRef.current.map(f => {
                    if (f.id === id) {
                        return { ...f, isUploading: false, filePath, progress: 100 };
                    }
                    return f;
                });
                setFiles(filesRef.current);

                remainingUploadsRef.current -= 1;
                if (remainingUploadsRef.current === 0) {
                    const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ path: f.filePath, name: f.name }));
                    onChange(uploadedFileIds);
                }
            }).catch(() => {
                toast({
                    variant: 'error',
                    description: t('chat.fileUploadFailed', { name: file.name }),
                });
                handleFileRemove(file.name);
                remainingUploadsRef.current -= 1;
                if (remainingUploadsRef.current === 0) {
                    const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ path: f.filePath, name: f.name }));
                    onChange(uploadedFileIds);
                }
            });
        });

        Promise.all(uploadPromises).then(() => {
            const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ path: f.filePath, name: f.name }));
            onChange(uploadedFileIds);
        });
    };

    const handleFileRemove = (fileName) => {
        const res = filesRef.current.filter(file => file.name !== fileName);
        filesRef.current = res
        setFiles(res);

        // If we manually remove a file during upload, we decrease the remaining upload counter
        remainingUploadsRef.current = Math.max(remainingUploadsRef.current - 1, 0);

        if (remainingUploadsRef.current === 0) {
            // If no files remain, trigger onChange immediately
            const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ path: f.filePath, name: f.name }));
            onChange(uploadedFileIds); // Trigger onChange with uploaded file IDs
        }
    };

    const formatFileSize = (size) => {
        let fileSize = typeof size === 'string' ? parseFloat(size) : size;
        const units = ['B', 'KB', 'MB', 'GB'];
        let index = 0;

        while (fileSize >= 1024 && index < units.length - 1) {
            fileSize /= 1024;
            index++;
        }

        return `${fileSize.toFixed(2)} ${units[index]}`;
    };

    useImperativeHandle(ref, () => ({
        upload: (fileList) => {
            if (disabled) return;
            handleFileChange(Array.from(fileList));
        }
    }));

    return (
        <div className="relative z-10">
            {/* Displaying files */}
            {!!files.length && <div className="absolute bottom-2 left-2 flex flex-wrap gap-2  bg-gray-50 p-2 rounded-xl max-h-96 overflow-y-auto">
                {files.map((file, index) => (
                    <div key={index} className="group relative flex items-center space-x-3 bg-gray-100 p-2 rounded-xl cursor-default">
                        {/* Remove button */}
                        <span
                            onClick={() => handleFileRemove(file.name)}
                            className="hidden group-hover:block absolute -right-1 -top-1 bg-gray-50 border-2 border-gray-300 text-gray-600 rounded-full cursor-pointer"
                        >
                            <X size={14} />
                        </span>

                        {/* File Icon */}
                        <div className="w-8 h-8 bg-gray-200 rounded-md flex items-center justify-center">
                            {file.isUploading ? <Loading className="size-4" /> : <FileIcon className="w-6 h-6 text-gray-600" />}
                        </div>

                        {/* File details */}
                        <div className="flex-1">
                            <div className="text-sm font-medium text-gray-700 truncate" title={file.name}>
                                {file.name}
                            </div>
                            {file.isUploading ? file.progress === 100
                                ? <div className="text-xs text-gray-500">{t('chat.fileParsingShort')}</div>
                                : <div className="text-xs text-gray-500">{t('chat.uploadingShort')} {file.progress}%</div>
                                : <div className="text-xs text-gray-500">{getFileExtension(file.name)} {formatFileSize(file.size)}</div>}
                        </div>
                    </div>
                ))}
            </div>}

            {/* File Upload Button */}
            <div
                className={`absolute right-10 top-5 cursor-pointer ${disabled ? 'text-gray-400 cursor-not-allowed' : ''}`}
                onClick={() => !disabled && fileInputRef.current.click()}
            >
                <PaperclipIcon size={18} />
            </div>

            {/* File Input */}
            <input
                type="file"
                ref={fileInputRef}
                multiple
                accept={accepts}
                onChange={(e) => handleFileChange(Array.from(e.target.files))}
                className="hidden"
            />
        </div>
    );
})
