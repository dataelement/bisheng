
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { uploadChatFile } from "~/api/apps";
import { MediaAttachmentChip } from "~/components/Chat/attachments/MediaAttachmentChip";
import { FileUploadThumbnail } from "~/components/Chat/attachments/UploadAttachmentThumbnail";
import { AttachmentIcon } from "~/components/svg";
import useLocalize from "~/hooks/useLocalize";
import { useToastContext } from "~/Providers";
import { cn, generateUUID } from "~/utils";
import {
    getMaxFileSizeBytesForFile,
    isMediaFileName,
    resolveUploadSizeLimits,
    type UploadSizeLimits,
} from "~/pages/knowledge/knowledgeUtils";
import { MAX_MEDIA_FILES } from "~/pages/appChat/fileAcceptUtils";
import { readMediaDurationFromFile, captureVideoPosterFromFile, getMediaKind, isMediaAttachmentFile } from "~/utils/mediaAttachmentUtils";

/** Unwrap BiSheng API envelope `{ status_code, data }` to the upload payload. */
const unwrapUploadPayload = (response: any) => {
    if (response?.status_code != null && response?.data != null) {
        return response.data;
    }
    if (response?.data?.filepath != null || response?.data?.file_path != null) {
        return response.data;
    }
    return response ?? {};
};

const notifyUploadedFiles = (getUploadedFileIds: () => any[], onChange: (files: any) => void) => {
    const uploaded = getUploadedFileIds();
    onChange(uploaded.length ? uploaded : []);
};

const logUploadStage = (fileName: string, stage: string, startedAt: number, extra?: Record<string, unknown>) => {
    const elapsedMs = Math.round(performance.now() - startedAt);
    console.info(`[client.media_upload] STAGE ${stage} elapsed_ms=${elapsedMs} file=${fileName}`, extra ?? '');
};

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
const InputFiles = forwardRef(({ v, showVoice, accepts, disabled = false, size, uploadSizeLimits, onChange, onFilesStateChange, uploadMode, hideTrigger = false, hideList = false }, ref) => {
    const t = useLocalize()
    const [files, setFiles] = useState([]);
    const filesRef = useRef([]);
    const remainingUploadsRef = useRef(0);
    const { showToast } = useToastContext();

    const fileInputRef = useRef(null);
    const resolvedLimits: UploadSizeLimits | null = uploadSizeLimits ?? null;
    const defaultFileSizeLimit = (size ?? 50) * 1024 * 1024;
    const defaultParsingStatus = uploadMode === 'linsight' ? 'running' : 'completed';
    const isLinsightParsing = (file) => {
        return uploadMode === 'linsight'
            && file?.parsingStatus
            && !['completed', 'failed'].includes(file.parsingStatus);
    };
    const getUploadedFileIds = () => filesRef.current
        .filter((f) => f.id && !f.isUploading && f.filePath)
        .map((f) => ({
        file_id: f.fileId || f.id,
        filepath: f.filePath,
        type: f.type,
        name: f.name,
        filename: f.name,
        file_name: f.name,
        parsing_status: f.parsingStatus || defaultParsingStatus,
        previewUrl: f.previewUrl,
        mediaPreviewUrl: f.mediaPreviewUrl,
        mediaCoverUrl: f.mediaCoverUrl,
        cover_filepath: f.cover_filepath,
        mediaDurationSec: f.mediaDurationSec,
    }));

    const handleFileChange = (selectedFiles) => {
        const validFiles = [];
        const invalidFiles = [];
        const invalidTypeFiles = [];
        const duplicateFiles = [];

        fileInputRef.current.value = ''
        // Block re-uploading a file already attached this round (filesRef stays in
        // sync with state) plus intra-batch dupes — the chat has no server-side
        // dedup. Scoped to the current turn since the list clears after send.
        const seenNames = new Set(filesRef.current.map((f) => f.name));
        const existingMediaCount = filesRef.current.filter((f) => isMediaFileName(f.name)).length;
        let incomingMediaCount = 0;
        // Validate files based on file extensions
        selectedFiles.forEach((file) => {
            if (!checkFileType(file, accepts)) {
                invalidTypeFiles.push(file);
                return;
            } else if (seenNames.has(file.name)) {
                duplicateFiles.push(file);
                return;
            }
            const maxBytes = resolvedLimits
                ? getMaxFileSizeBytesForFile(file.name, resolvedLimits)
                : defaultFileSizeLimit;
            if (isMediaFileName(file.name)) {
                incomingMediaCount += 1;
            }
            if (file.size <= maxBytes) {
                seenNames.add(file.name);
                validFiles.push({ id: generateUUID(6), file });
            } else {
                invalidFiles.push({ id: generateUUID(6), file });
            }
        });

        if (existingMediaCount + incomingMediaCount > MAX_MEDIA_FILES) {
            showToast({ message: t('com_chat.media_file_too_many'), status: 'error' });
            return;
        }

        if (invalidTypeFiles.length > 0) {
            showToast({ message: t('com_ui_upload_file_type_error'), status: 'error' }); // 请确保你有对应多语言key或直接写死中文测试
        }
        // Notify about skipped duplicates
        if (duplicateFiles.length > 0) {
            showToast({ message: t('com_error_files_dupe'), status: 'info' });
        }
        // Show invalid file toast
        if (invalidFiles.length > 0) {
            invalidFiles.map(file =>
                showToast({
                    message: isMediaFileName(file.file.name)
                        ? t('com_chat.media_file_too_large')
                        : t('com_inputfiles_exceed_limit', { 0: file.file.name, 1: size }),
                    status: 'info',
                })
            )
        }

        if (!validFiles.length) return;

        // Trigger onChange with null to indicate uploading state
        onChange(null);

        // Add valid files to state with initial progress
        const filesWithProgress = validFiles.map(({ file, id }) => {
            const isMedia = isMediaFileName(file.name);
            return {
                name: file.name,
                size: file.size,
                type: file.type,
                isUploading: true,
                progress: 0,
                id,
                file,
                previewUrl: file.type?.startsWith('image/') ? URL.createObjectURL(file) : undefined,
                mediaPreviewUrl: isMedia ? URL.createObjectURL(file) : undefined,
                mediaDurationSec: undefined,
            };
        });

        if (validFiles.some(({ file }) => isMediaFileName(file.name))) {
            validFiles.forEach(({ file, id }) => {
                if (!isMediaFileName(file.name)) return;
                readMediaDurationFromFile(file).then((mediaDurationSec) => {
                    if (mediaDurationSec == null) return;
                    setFiles((prevFiles) => {
                        const updated = prevFiles.map((f) =>
                            f.id === id ? { ...f, mediaDurationSec } : f,
                        );
                        filesRef.current = updated;
                        onFilesStateChange?.(updated);
                        return updated;
                    });
                });
                if (getMediaKind(file.name) === 'video') {
                    captureVideoPosterFromFile(file).then((mediaCoverUrl) => {
                        if (!mediaCoverUrl) return;
                        setFiles((prevFiles) => {
                            const updated = prevFiles.map((f) =>
                                f.id === id ? { ...f, mediaCoverUrl } : f,
                            );
                            filesRef.current = updated;
                            onFilesStateChange?.(updated);
                            return updated;
                        });
                    });
                }
            });
        }

        setFiles(prevFiles => {
            const res = [...prevFiles, ...filesWithProgress];
            filesRef.current = res;
            onFilesStateChange?.(res);
            return res;
        });

        // Keep track of the number of remaining uploads across concurrent batches.
        remainingUploadsRef.current += validFiles.length;

        // Create an array of promises to handle multiple file uploads concurrently
        const uploadPromises = validFiles.map(({ file, id }) => {
            const uploadStartedAt = performance.now();
            logUploadStage(file.name, 'queue', uploadStartedAt, { size: file.size, type: file.type });
            let lastLoggedProgress = -1;
            return uploadChatFile(v, file, (progress) => {
                if (progress >= 100 && lastLoggedProgress < 100) {
                    logUploadStage(file.name, 'xhr_upload_complete', uploadStartedAt, { progress });
                    lastLoggedProgress = 100;
                } else if (progress - lastLoggedProgress >= 25) {
                    logUploadStage(file.name, 'xhr_progress', uploadStartedAt, { progress });
                    lastLoggedProgress = progress;
                }
                // Update progress for each file individually
                setFiles((prevFiles) => {
                    const updatedFiles = prevFiles.map(f => {
                        if (f.id === id) {
                            return { ...f, progress }; // Update progress for the specific file
                        }
                        return f;
                    });
                    filesRef.current = updatedFiles;
                    onFilesStateChange?.(updatedFiles);
                    return updatedFiles;
                });
            }, uploadMode).then(response => {
                logUploadStage(file.name, 'api_response', uploadStartedAt, {
                    status_code: response?.status_code,
                });
                if (response?.status_code != null && response.status_code !== 200) {
                    throw new Error(response.status_message || 'upload failed');
                }
                const responseData = unwrapUploadPayload(response);
                // Upload API returns `filepath` (no underscore). Keep `file_path` fallback
                // for any caller/endpoint that still uses the snake-case form.
                const filePath = responseData.filepath ?? responseData.file_path;
                if (!filePath) {
                    throw new Error('upload response missing filepath');
                }
                logUploadStage(file.name, 'parsed_filepath', uploadStartedAt, {
                    filepath: filePath,
                    cover_filepath: responseData.cover_filepath,
                });
                const fileId = responseData.file_id; // Server-returned file_id
                const coverFilepath = responseData.cover_filepath;
                const parsingStatus = responseData.parsing_status ?? defaultParsingStatus;
                filesRef.current = filesRef.current.map(f => {
                    if (f.id === id) {
                        const next = {
                            ...f,
                            isUploading: false,
                            filePath,
                            fileId,
                            parsingStatus,
                            progress: 100,
                            ...(coverFilepath ? { cover_filepath: coverFilepath } : {}),
                        };
                        if (coverFilepath && f.mediaCoverUrl?.startsWith('blob:')) {
                            URL.revokeObjectURL(f.mediaCoverUrl);
                            next.mediaCoverUrl = undefined;
                        }
                        return next;
                    }
                    return f;
                });
                setFiles(filesRef.current);
                onFilesStateChange?.(filesRef.current);

                remainingUploadsRef.current -= 1; // Decrease the remaining uploads count
                notifyUploadedFiles(getUploadedFileIds, onChange);
                logUploadStage(file.name, 'state_committed', uploadStartedAt);
            }).catch((e) => {
                logUploadStage(file.name, 'failed', uploadStartedAt, { error: String(e) });
                console.log('e :>> ', e);
                showToast({ message: t('com_inputfiles_upload_failed', { 0: file.name }), status: 'error' })
                handleFileRemove(file.name);
                remainingUploadsRef.current -= 1; // Decrease the remaining uploads count
                notifyUploadedFiles(getUploadedFileIds, onChange);
            });
        });

        // Wait for all files to finish uploading
        Promise.all(uploadPromises).then(() => {
            notifyUploadedFiles(getUploadedFileIds, onChange);
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
        updateParsingStatus: (statusMap) => {
            setFiles((prevFiles) => {
                const updatedFiles = prevFiles.reduce((result, file) => {
                    const fileId = file.fileId || file.file_id;
                    const status = statusMap?.get?.(fileId);

                    if (!status) {
                        result.push(file);
                        return result;
                    }

                    if (status === 'failed') {
                        return result;
                    }

                    result.push({ ...file, parsingStatus: status, isUploading: false });
                    return result;
                }, []);

                filesRef.current = updatedFiles;
                onFilesStateChange?.(updatedFiles);
                return updatedFiles;
            });
        },
        openPicker: () => {
            if (disabled) return;
            fileInputRef.current?.click();
        },
        clear: () => {
            filesRef.current.forEach(f => {
                if (f.previewUrl) URL.revokeObjectURL(f.previewUrl);
                if (f.mediaPreviewUrl) URL.revokeObjectURL(f.mediaPreviewUrl);
                if (f.mediaCoverUrl?.startsWith('blob:')) URL.revokeObjectURL(f.mediaCoverUrl);
            });
            setFiles([]);
            filesRef.current = [];
            onFilesStateChange?.([]);
            onChange([]);
        }
    }));

    // Release any live object URLs when the component unmounts so pinned image
    // previews don't leak blobs.
    useEffect(() => () => {
        filesRef.current.forEach(f => {
            if (f.previewUrl) URL.revokeObjectURL(f.previewUrl);
            if (f.mediaPreviewUrl) URL.revokeObjectURL(f.mediaPreviewUrl);
            if (f.mediaCoverUrl?.startsWith('blob:')) URL.revokeObjectURL(f.mediaCoverUrl);
        });
    }, []);

    const handleFileRemove = (fileName) => {
        const removed = filesRef.current.find(file => file.name === fileName);
        if (removed?.previewUrl) URL.revokeObjectURL(removed.previewUrl);
        if (removed?.mediaPreviewUrl) URL.revokeObjectURL(removed.mediaPreviewUrl);
        if (removed?.mediaCoverUrl?.startsWith('blob:')) URL.revokeObjectURL(removed.mediaCoverUrl);
        const res = filesRef.current.filter(file => file.name !== fileName);
        filesRef.current = res
        setFiles(res);
        onFilesStateChange?.(res);

        // If we manually remove a file during upload, we decrease the remaining upload counter
        remainingUploadsRef.current = Math.max(remainingUploadsRef.current - 1, 0);

        if (remainingUploadsRef.current === 0) {
            // If no files remain, trigger onChange immediately
            const uploadedFileIds = getUploadedFileIds();
            onChange(uploadedFileIds); // Trigger onChange with uploaded file IDs
        }
    };

    const renderInlineFileChip = (file, index) => {
        const isMedia = isMediaAttachmentFile({ name: file.name });
        const isParsing = isLinsightParsing(file);

        if (isMedia) {
            return (
                <MediaAttachmentChip
                    key={file.id || index}
                    file={{
                        name: file.name,
                        filepath: file.filePath,
                        cover_filepath: file.cover_filepath,
                        isUploading: file.isUploading || isParsing,
                        mediaPreviewUrl: file.mediaPreviewUrl,
                        mediaCoverUrl: file.mediaCoverUrl,
                        mediaDurationSec: file.mediaDurationSec,
                        parsingState: isParsing ? 'parsing' : undefined,
                    }}
                    onRemove={() => handleFileRemove(file.name)}
                    variant="bar"
                />
            );
        }

        return (
            <FileUploadThumbnail
                key={file.id || index}
                fileName={file.name}
                previewUrl={/\.(png|jpe?g|bmp|gif|webp)$/i.test(file.name) ? file.previewUrl : undefined}
                variant="bar"
                isUploading={file.isUploading || isParsing}
                onRemove={() => handleFileRemove(file.name)}
            />
        );
    };

    return (
        <div className="">
            {/* Displaying files */}
            {!hideList && !!files.length && (
                <div className="flex max-w-full gap-2 overflow-x-auto overflow-y-hidden p-2 pb-3">
                    {files.map(renderInlineFileChip)}
                </div>
            )}

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
