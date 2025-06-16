import { useToast } from "@/components/bs-ui/toast/use-toast";
import { generateUUID } from "@/components/bs-ui/utils";
import Loading from "@/components/ui/loading";
import { locationContext } from "@/contexts/locationContext";
import { uploadChatFile } from "@/controllers/API/flow";
import { getFileExtension } from "@/util/utils";
import { FileIcon, PaperclipIcon, X } from "lucide-react";
import { forwardRef, useContext, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";

// @accepts '.png,.jpg'
const ChatFiles = forwardRef(({ v, accepts, onChange, preParsing }, ref) => {
    const [files, setFiles] = useState([]);
    const filesRef = useRef([]);
    const remainingUploadsRef = useRef(0);
    const { appConfig } = useContext(locationContext);
    const fileAccepts = useMemo(() => appConfig.libAccepts.map((ext) => `.${ext}`), [appConfig.libAccepts]);
    const { toast } = useToast();
    const containerRef = useRef(null); // 新增：用于监听高度的容器 ref
    const [containerHeight, setContainerHeight] = useState(0); // 新增：存储高度

    const fileInputRef = useRef(null);
    const fileSizeLimit = appConfig.uploadFileMaxSize * 1024 * 1024; // File size limit in bytes

    const handleFileChange = (e) => {
        const selectedFiles = Array.from(e.target.files);
        const validFiles = [];
        const invalidFiles = [];

        fileInputRef.current.value = ''
        // Validate files based on file extensions
        selectedFiles.forEach((file) => {
            if (file.size <= fileSizeLimit) {
                validFiles.push({ id: generateUUID(6), file });
            } else {
                invalidFiles.push({ id: generateUUID(6), file });
            }
        });

        // Show invalid file toast
        if (invalidFiles.length > 0) {
            toast({
                variant: 'info',
                description: invalidFiles.map(file => `文件：${file.file.name}超过${appConfig.uploadFileMaxSize}M，已移除`),
            });
        }

        if (!validFiles.length) return;

        // Trigger onChange with null to indicate uploading state
        onChange(null);

        // Add valid files to state with initial progress
        const filesWithProgress = validFiles.map(({ file, id }) => {
            return {
                name: file.name,
                size: file.size,
                type: file.type,
                isUploading: true,
                progress: 0, // Set initial progress to 0
                id, // Use the generated id
                file // Keep original file object for later use
            };
        });

        setFiles(prevFiles => {
            const res = [...prevFiles, ...filesWithProgress];
            filesRef.current = res;
            return res;
        });

        // Keep track of the number of remaining uploads
        remainingUploadsRef.current = validFiles.length;

        // Create an array of promises to handle multiple file uploads concurrently
        const uploadPromises = validFiles.map(({ file, id }) => {
            return uploadChatFile(file, (progress) => {
                // Update progress for each file individually
                setFiles((prevFiles) => {
                    const updatedFiles = prevFiles.map(f => {
                        if (f.id === id) {
                            return { ...f, progress }; // Update progress for the specific file
                        }
                        return f;
                    });
                    filesRef.current = updatedFiles;
                    return updatedFiles;
                });
            }, preParsing, v).then(response => {
                const filePath = response.file_path || response.id; // Assuming the response contains the file ID
                filesRef.current = filesRef.current.map(f => {
                    if (f.id === id) {
                        return { ...f, isUploading: false, filePath, progress: 100 }; // Set progress to 100 when uploaded
                    }
                    return f;
                });
                setFiles(filesRef.current);

                remainingUploadsRef.current -= 1; // Decrease the remaining uploads count
                if (remainingUploadsRef.current === 0) {
                    // Once all files are uploaded, trigger onChange with the file IDs
                    const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ path: f.filePath, name: f.name }));
                    onChange(uploadedFileIds); // Pass the file IDs to onChange
                }
            }).catch(() => {
                // Handle upload failure
                toast({
                    variant: 'error',
                    description: `文件上传失败: ${file.name}`,
                });
                handleFileRemove(file.name);
                remainingUploadsRef.current -= 1; // Decrease the remaining uploads count
                if (remainingUploadsRef.current === 0) {
                    // If no files remain, trigger onChange immediately
                    const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ path: f.filePath, name: f.name }));
                    onChange(uploadedFileIds);
                }
            });
        });

        // Wait for all files to finish uploading
        Promise.all(uploadPromises).then(() => {
            // Once all files are uploaded, trigger onChange with the file IDs
            const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ path: f.filePath, name: f.name }));
            onChange(uploadedFileIds); // Pass the file IDs to onChange
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
            const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ id: f.id, name: f.name }));
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

    // 监听容器高度变化
    useEffect(() => {
        if (!containerRef.current) return;

        const observer = new ResizeObserver((entries) => {
            const { height } = entries[0].contentRect;
            console.log('内部height', height);
            
            setContainerHeight(height);
        });

        observer.observe(containerRef.current);
        return () => observer.disconnect(); // 清理观察器
    }, [files]); // 依赖 files 变化重新计算高度

    // 暴露高度给父组件
    useImperativeHandle(ref, () => ({
        getHeight: () => containerHeight,
    }));
    return (
        <div className="relative z-10">
            {/* Displaying files */}
            {!!files.length && <div
                ref={containerRef}
                className="absolute bottom-2 left-2 flex flex-wrap gap-2 bg-gray-50 p-2 rounded-xl max-h-[180px] overflow-y-auto"
            >
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
                                ? <div className="text-xs text-gray-500">解析中...</div>
                                : <div className="text-xs text-gray-500">上传中... {file.progress}%</div>
                                : <div className="text-xs text-gray-500">{getFileExtension(file.name)} {formatFileSize(file.size)}</div>}
                        </div>
                    </div>
                ))}
            </div>}

            {/* File Upload Button */}
            <div className="absolute right-20 top-5 cursor-pointer" onClick={() => fileInputRef.current.click()}>
                <PaperclipIcon size={18} />
            </div>

            {/* File Input */}
            <input
                type="file"
                ref={fileInputRef}
                multiple
                accept={accepts || fileAccepts.join(',')}
                onChange={handleFileChange}
                className="hidden"
            />
        </div>
    );
})

export default ChatFiles;