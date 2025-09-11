
import { X } from "lucide-react";
import { useRef, useState } from "react";
import { uploadChatFile } from "~/api/apps";
import { AttachmentIcon } from "~/components/svg";
import { FileIcon, getFileTypebyFileName } from "~/components/ui/icon/File/FileIcon";
import { useToastContext } from "~/Providers";
import { generateUUID, getFileExtension } from "~/utils";

// @accepts '.png,.jpg'
export default function InputFiles({ v, accepts, size, onChange }) {
    const [files, setFiles] = useState([]);
    const filesRef = useRef([]);
    const remainingUploadsRef = useRef(0);
    const { showToast } = useToastContext();

    const fileInputRef = useRef(null);
    const fileSizeLimit = size * 1024 * 1024; // File size limit in bytes

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
            invalidFiles.map(file =>
                showToast({ message: `文件：${file.file.name}超过${size}M，已移除`, status: 'info' })
            )
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
            return uploadChatFile(v, file, (progress) => {
                console.log('progress :>> ', progress);
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
            }).then(response => {
                const filePath = response.data.file_path; // Assuming the response contains the file ID
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
            }).catch((e) => {
                console.log('e :>> ', e);
                showToast({ message: `文件上传失败: ${file.name}`, status: 'error' })
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

    return (
        <div className="">
            {/* Displaying files */}
            {!!files.length && <div className="flex flex-wrap gap-2 p-2 rounded-xl max-h-96 overflow-y-auto">
                {files.map((file, index) => (
                    <div key={index} className="group min-w-52 relative flex items-center gap-2 border bg-white p-2 rounded-2xl cursor-default">
                        {/* Remove button */}
                        <span
                            onClick={() => handleFileRemove(file.name)}
                            className="opacity-0 group-hover:opacity-100 absolute p-0.5 right-1.5 top-1.5 bg-black text-white rounded-full cursor-pointer transition-opacity"
                        >
                            <X size={14} />
                        </span>

                        {/* File Icon */}
                        <FileIcon loading={file.isUploading} type={getFileTypebyFileName(file.name)} />

                        {/* File details */}
                        <div className="flex-1">
                            <div className="max-w-48 text-sm font-medium text-gray-700 truncate" title={file.name}>
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
            <div className="absolute right-14 bottom-3 cursor-pointer p-1 hover:bg-gray-200 rounded-full" onClick={() => fileInputRef.current.click()}>
                <AttachmentIcon />
            </div>

            {/* File Input */}
            <input
                type="file"
                ref={fileInputRef}
                multiple
                accept={accepts}
                onChange={handleFileChange}
                className="hidden"
            />
        </div>
    );
}
