// @ts-strict-ignore
import { notification } from '@bisheng/ui';

import { generateUUID } from "@/components/bs-ui/utils";
import Loading from "@/components/ui/loading";
import { locationContext } from "@/contexts/locationContext";
import { uploadArchive } from "@/controllers/API/archiveUpload";
import { uploadChatFile } from "@/controllers/API/flow";
import { showApiError } from '@/controllers/request';
import { MAX_MEDIA_FILES,isMediaFileName } from "@/util/fileAcceptUtils";
import { getFileExtension } from "@/util/utils";
import { Outlined } from "bisheng-icons";

import { forwardRef,useContext,useImperativeHandle,useRef,useState } from "react";
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


export interface ChatFilesHandle {
    openPicker: () => void;
    upload: (files: FileList | File[]) => void;
}
interface ChatFilesProps {
    v: string;
    accepts?: string;
    disabled?: boolean;
    onChange: (files: { path: string; name: string }[] | null) => void;
}

// @accepts '.png,.jpg'
export default forwardRef<ChatFilesHandle, ChatFilesProps>(function ChatFiles({ v, accepts, disabled, onChange }, ref) {

    const { t } = useTranslation();
    const [files, setFiles] = useState([]);
    const filesRef = useRef([]);
    const remainingUploadsRef = useRef(0);
    const controllers = useRef(new Map<string, AbortController>());
    const publishFiles = () => onChange(filesRef.current.some(f => f.isUploading)
        ? null : filesRef.current.filter(f => f.filePath).map(f => ({path:f.filePath,name:f.name})));
    const { appConfig } = useContext(locationContext);
    // const fileAccepts = useMemo(() => appConfig.libAccepts.map((ext) => `.${ext}`), [appConfig.libAccepts]);


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
                return notification.open({ type: 'error', description: String(t('com_ui_upload_file_type_error') ?? '') }); // 请确保你有对应多语言key或直接写死中文测试
            }
            // 2. 再校验文件大小
            if (file.size > fileSizeLimit) {
                invalidTips.push(t('chat.fileExceedRemoved', { name: file.name, size: appConfig.uploadFileMaxSize }));
                return; // 大小不符合，跳过
            }

            // 3. 所有校验通过，加入有效文件列表
            validFiles.push({ id: generateUUID(6), file });
        });

        // Audio/video is transcribed, not text-extracted: every clip holds an ASR
        // slot for the whole run. Same cap the end-user chat enforces (client
        // `InputFiles`), counting what is already attached this round.
        const existingMediaCount = filesRef.current.filter((f) => isMediaFileName(f.name)).length;
        const incomingMediaCount = validFiles.filter(({ file }) => isMediaFileName(file.name)).length;
        if (existingMediaCount + incomingMediaCount > MAX_MEDIA_FILES) {
            return notification.open({ type: 'error', description: String(t('chat.mediaFileTooMany') ?? '') });
        }

        // 显示无效文件提示（区分类型/大小错误）
        if (invalidTips.length > 0) {
            notification.open({ type: 'info', description: String(invalidTips.join('\n') ?? '') });
        }

        // 只要有有效文件就继续上传流程
        if (!validFiles.length) return;

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

        filesRef.current = [...filesRef.current, ...filesWithProgress];
        setFiles(filesRef.current);

        remainingUploadsRef.current += validFiles.length;

        const uploadFactories = validFiles.map(({ file, id }) => () => {
            if (!filesRef.current.some(f => f.id === id)) return Promise.resolve();
            const controller = new AbortController();
            controllers.current.set(id, controller);
            const uploadTask = file.name.toLowerCase().endsWith('.zip')
                ? uploadArchive(file, accepts, controller.signal).then(children => ({ archive_files: children }))
                : uploadChatFile(v, file, (progress) => {
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
            });
            return uploadTask.then(response => {
                if (!filesRef.current.some(f => f.id === id)) return;
                if (Array.isArray(response.archive_files)) {
                    const others = filesRef.current.filter(f => f.id !== id);
                    const children = response.archive_files.map(child => ({
                        id: child.file_id, name: child.display_name, filePath: child.file_path,
                        size: child.size, archiveId: child.archive_id, isUploading: false, progress: 100,
                    }));
                    if (others.length + children.length > 20 || [...others,...children].reduce((sum,f) => sum+(f.size||0),0)>100*1024*1024) {
                        notification.open({ type: 'error', description: t('chat.archiveBatchLimit') });
                        handleFileRemove(id);
                        return;
                    }
                    filesRef.current = [...others, ...children];
                    setFiles(filesRef.current);
                    remainingUploadsRef.current = Math.max(remainingUploadsRef.current - 1, 0);
                    publishFiles();
                    return;
                }
                const filePath = response.file_path;
                filesRef.current = filesRef.current.map(f => {
                    if (f.id === id) {
                        return { ...f, isUploading: false, filePath, progress: 100 };
                    }
                    return f;
                });
                setFiles(filesRef.current);

                remainingUploadsRef.current = Math.max(remainingUploadsRef.current - 1, 0);
                if (remainingUploadsRef.current === 0) {
                    publishFiles();
                }
            }).catch((error) => {
                if (!filesRef.current.some(file => file.id === id)) return;
                showApiError(error);
                handleFileRemove(id);
            }).finally(() => {
                controllers.current.delete(id);
            });
        });

        void uploadFactories.reduce((chain, upload) => chain.then(upload), Promise.resolve()).catch(showApiError);
    };

    const handleFileRemove = (fileId) => {
        const removed = filesRef.current.filter(file => file.id === fileId);
        if (!removed.length) return;
        const pendingRemoved = removed.filter(file => file.isUploading).length;
        controllers.current.get(fileId)?.abort();
        controllers.current.delete(fileId);
        const res = filesRef.current.filter(file => file.id !== fileId);
        filesRef.current = res
        setFiles(res);

        // Count each pending attachment exactly once, including manual removal.
        remainingUploadsRef.current = Math.max(remainingUploadsRef.current - pendingRemoved, 0);

        if (remainingUploadsRef.current === 0) {
            // If no files remain, trigger onChange immediately
            publishFiles();
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
        openPicker: () => { if (!disabled) fileInputRef.current?.click(); },
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
                            onClick={() => handleFileRemove(file.id)}
                            className="hidden group-hover:block absolute -right-1 -top-1 bg-gray-50 border-2 border-gray-300 text-gray-600 rounded-full cursor-pointer"
                        >
                            <Outlined.Close size={14} />
                        </span>

                        {/* File Icon */}
                        <div className="w-8 h-8 bg-gray-200 rounded-md flex items-center justify-center">
                            {file.isUploading ? <Loading className="size-4" /> : <Outlined.File className="w-6 h-6 text-gray-600" />}
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
