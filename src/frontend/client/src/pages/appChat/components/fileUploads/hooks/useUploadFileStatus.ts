import { useCallback, useEffect, useRef, type Dispatch, type MutableRefObject, type SetStateAction } from 'react';
import { checkFileParseStatus } from '~/api/linsight';
import { applyParseStatusToFile, isUploadFileParsing, type ParseStatusEntry, type UploadAttachment } from '../uploadUtils';

type UploadFileStatusOptions<T extends UploadAttachment> = {
    files: T[];
    filesRef: MutableRefObject<T[]>;
    setFiles: Dispatch<SetStateAction<T[]>>;
    uploadMode?: string;
    onFilesStateChange?: (files: T[]) => void;
    publishFiles: () => void;
};

export function useUploadFileStatus<T extends UploadAttachment>({ files, filesRef, setFiles, uploadMode,
    onFilesStateChange, publishFiles }: UploadFileStatusOptions<T>) {
    // Keep notifications current without restarting polling for callback identity changes.
    const callbacks = useRef({ onFilesStateChange, publishFiles });
    callbacks.current = { onFilesStateChange, publishFiles };

    // Release any live object URLs when the component unmounts so pinned image
    // previews don't leak blobs.
    useEffect(() => () => {
        filesRef.current.forEach(f => {
            if (f.previewUrl) URL.revokeObjectURL(f.previewUrl);
            if (f.mediaPreviewUrl) URL.revokeObjectURL(f.mediaPreviewUrl);
            if (f.mediaCoverUrl?.startsWith('blob:')) URL.revokeObjectURL(f.mediaCoverUrl);
        });
    }, [filesRef]);

    const mergeParseStatusUpdates = useCallback((updates: Map<string, ParseStatusEntry>) => {
        if (!updates.size) return;

        // Derived from filesRef, not inside a setFiles updater: updaters run during
        // render, and the parent notifications below would then update AiChatInput
        // mid-render — React warns ("Cannot update a component while rendering a
        // different component") and drops the update.
        let changed = false;
        const nextFiles = filesRef.current.reduce<T[]>((result, file) => {
            const fileId = file.fileId || file.file_id;
            const entry = fileId ? updates.get(fileId) : undefined;
            if (!entry) {
                result.push(file);
                return result;
            }
            if (entry.parsing_status === 'failed') {
                changed = true;
                return result;
            }
            const nextFile = applyParseStatusToFile(file, entry);
            if (!nextFile) {
                return result;
            }
            changed = changed
                || nextFile.parsingStatus !== file.parsingStatus
                || nextFile.cover_filepath !== file.cover_filepath;
            result.push(nextFile);
            return result;
        }, []);

        if (!changed) return;
        filesRef.current = nextFiles;
        setFiles(nextFiles);
        callbacks.current.onFilesStateChange?.(nextFiles);
        callbacks.current.publishFiles();
    }, [filesRef, setFiles]);

    // Poll linsight upload parse status (ASR, etc.) until completed.
    useEffect(() => {
        if (uploadMode !== 'linsight') return;

        const pending = filesRef.current.filter((file) => {
            const fileId = file.fileId || file.file_id;
            return fileId && isUploadFileParsing(file, uploadMode);
        });
        if (!pending.length) return;

        const intervalId = window.setInterval(async () => {
            try {
                const res = await checkFileParseStatus(
                    pending.map((file) => String(file.fileId || file.file_id)),
                );
                const statusList = Array.isArray(res.data) ? res.data.filter(Boolean) : [];
                const updates = new Map<string, ParseStatusEntry>();
                statusList.forEach((item: ParseStatusEntry & { file_id?: string }) => {
                    if (item?.file_id) {
                        updates.set(String(item.file_id), item);
                    }
                });
                mergeParseStatusUpdates(updates);
            } catch (error) {
                console.error('Media file parsing status check failed:', error);
            }
        }, 2000);

        return () => window.clearInterval(intervalId);
    }, [files, filesRef, mergeParseStatusUpdates, uploadMode]);

}
