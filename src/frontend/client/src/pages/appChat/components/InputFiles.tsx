
import { Loader2, X } from "lucide-react";
import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { uploadChatFile } from "~/api/apps";
import { AttachmentIcon } from "~/components/svg";
import { getFileTypebyFileName } from "~/components/ui/icon/File/FileIcon";
import LegacyFileIcon from "~/components/ui/icon/File";
import useLocalize from "~/hooks/useLocalize";
import { useToastContext } from "~/Providers";
import { cn, generateUUID } from "~/utils";

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
// `hideTrigger` hides the built-in attachment icon; caller invokes
// `openPicker()` via the imperative ref (e.g. from the "+" menu).
const InputFiles = forwardRef(({ v, showVoice, accepts, disabled = false, size, onChange, uploadMode, hideTrigger = false, hideList = false }, ref) => {
    const t = useLocalize()
    const [files, setFiles] = useState([]);
    const filesRef = useRef([]);
    const remainingUploadsRef = useRef(0);
    const { showToast } = useToastContext();

    const fileInputRef = useRef(null);
    const fileSizeLimit = size * 1024 * 1024; // File size limit in bytes

    const handleFileChange = (selectedFiles) => {
        const validFiles = [];
        const invalidFiles = [];
        const invalidTypeFiles = [];

        fileInputRef.current.value = ''
        // Validate files based on file extensions
        selectedFiles.forEach((file) => {
            if (!checkFileType(file, accepts)) {
                invalidTypeFiles.push(file);
                return;
            } else if (file.size <= fileSizeLimit) {
                validFiles.push({ id: generateUUID(6), file });
            } else {
                invalidFiles.push({ id: generateUUID(6), file });
            }
        });

        if (invalidTypeFiles.length > 0) {
            showToast({ message: t('com_ui_upload_file_type_error'), status: 'error' }); // 请确保你有对应多语言key或直接写死中文测试
        }
        // Show invalid file toast
        if (invalidFiles.length > 0) {
            invalidFiles.map(file =>
                showToast({ message: t('com_inputfiles_exceed_limit', { 0: file.file.name, 1: size }), status: 'info' })
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
            }, uploadMode).then(response => {
                // Upload API returns `filepath` (no underscore). Keep `file_path` fallback
                // for any caller/endpoint that still uses the snake-case form.
                const filePath = response.data.filepath ?? response.data.file_path;
                const fileId = response.data.file_id; // Server-returned file_id
                filesRef.current = filesRef.current.map(f => {
                    if (f.id === id) {
                        return { ...f, isUploading: false, filePath, fileId, progress: 100 }; // Set progress to 100 when uploaded
                    }
                    return f;
                });
                setFiles(filesRef.current);

                remainingUploadsRef.current -= 1; // Decrease the remaining uploads count
                if (remainingUploadsRef.current === 0) {
                    // Once all files are uploaded, trigger onChange with the file IDs
                    const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ file_id: f.fileId || f.id, filepath: f.filePath, type: f.type, name: f.name }));
                    onChange(uploadedFileIds); // Pass the file IDs to onChange
                }
            }).catch((e) => {
                console.log('e :>> ', e);
                showToast({ message: t('com_inputfiles_upload_failed', { 0: file.name }), status: 'error' })
                handleFileRemove(file.name);
                remainingUploadsRef.current -= 1; // Decrease the remaining uploads count
                if (remainingUploadsRef.current === 0) {
                    // If no files remain, trigger onChange immediately
                    const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ file_id: f.fileId || f.id, filepath: f.filePath, type: f.type, name: f.name }));
                    onChange(uploadedFileIds);
                }
            });
        });

        // Wait for all files to finish uploading
        Promise.all(uploadPromises).then(() => {
            // Once all files are uploaded, trigger onChange with the file IDs
            const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ file_id: f.fileId || f.id, filepath: f.filePath, type: f.type, name: f.name }));
            onChange(uploadedFileIds); // Pass the file IDs to onChange
        });
    };

    useImperativeHandle(ref, () => ({
        upload: (fileList) => {
            if (disabled) return;
            handleFileChange(Array.from(fileList));
        },
        removeByName: (fileName) => {
            handleFileRemove(fileName);
        },
        openPicker: () => {
            if (disabled) return;
            fileInputRef.current?.click();
        },
        clear: () => {
            setFiles([]);
            filesRef.current = [];
            onChange([]);
        }
    }));

    const handleFileRemove = (fileName) => {
        const res = filesRef.current.filter(file => file.name !== fileName);
        filesRef.current = res
        setFiles(res);

        // If we manually remove a file during upload, we decrease the remaining upload counter
        remainingUploadsRef.current = Math.max(remainingUploadsRef.current - 1, 0);

        if (remainingUploadsRef.current === 0) {
            // If no files remain, trigger onChange immediately
            const uploadedFileIds = filesRef.current.filter(f => f.id).map(f => ({ file_id: f.fileId || f.id, filepath: f.filePath, type: f.type, name: f.name }));
            onChange(uploadedFileIds); // Trigger onChange with uploaded file IDs
        }
    };

    return (
        <div className="">
            {/* Displaying files */}
            {!hideList && !!files.length && <div className="flex max-w-full flex-nowrap gap-1 overflow-x-auto overflow-y-hidden p-2">
                {files.map((file, index) => (
                    <div
                        key={index}
                        className="group inline-flex h-6 min-w-0 max-w-[220px] shrink-0 items-center rounded-[4px] bg-white px-2 text-xs text-slate-700 transition-colors duration-200 hover:bg-slate-50"
                    >
                        {file.isUploading ? (
                            <Loader2 className="mr-1 size-4 shrink-0 animate-spin text-[#999]" />
                        ) : (
                            <LegacyFileIcon className="mr-1 size-4 shrink-0 text-[#999]" type={getFileTypebyFileName(file.name)} />
                        )}
                        <span className="min-w-0 flex-1 truncate text-left" title={file.name}>
                            {file.name}
                        </span>
                        <button
                            type="button"
                            onClick={() => handleFileRemove(file.name)}
                            className="ml-0.5 inline-flex size-4 shrink-0 items-center justify-center rounded-full text-slate-400 transition-colors hover:bg-slate-200"
                            aria-label="Remove file"
                        >
                            <X size={12} />
                        </button>
                    </div>
                ))}
            </div>}

            {/* File Upload Button — hidden when invoked from the "+" menu. */}
            {!hideTrigger && (
                <div
                    className={cn(
                        'absolute z-10 bottom-3 cursor-pointer p-1 hover:bg-gray-200 rounded-full',
                        showVoice ? 'right-[92px]' : 'right-14',
                        disabled ? 'pointer-events-none opacity-40' : ''
                    )}
                    onClick={() => !disabled && fileInputRef.current.click()}
                >
                    <AttachmentIcon />
                </div>
            )}

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
});

export default InputFiles;
