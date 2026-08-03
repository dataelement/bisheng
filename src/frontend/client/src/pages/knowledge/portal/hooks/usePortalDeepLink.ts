import { useEffect, useMemo, useRef, type Dispatch, type RefObject, type SetStateAction } from "react";
import {
    FileStatus,
    FileType,
    KnowledgeFile,
    KnowledgeSpace,
    searchSpaceChildrenApi,
} from "~/api/knowledge";
import { TREE_PAGE_SIZE } from "../constants";
import { isFolder } from "../utils";

export interface PortalDeepLinkTarget {
    spaceId: string;
    folderId: string;
    folderName: string;
    fileId: string;
    fileName: string;
    /** Forces re-apply when the same file is opened again via postMessage. */
    openNonce: string;
    key: string;
}

interface UsePortalDeepLinkParams {
    searchParams: URLSearchParams;
    activeSpace: KnowledgeSpace | null;
    activeSpaceIdRef: RefObject<string | undefined>;
    selectableSpaces: KnowledgeSpace[];
    displayedFiles: KnowledgeFile[];
    statusFilterNumbers: number[];
    setActiveSpace: Dispatch<SetStateAction<KnowledgeSpace | null>>;
    setCurrentFolderId: Dispatch<SetStateAction<string | undefined>>;
    setSelectedFileIds: Dispatch<SetStateAction<Set<string>>>;
    setSelectedFolderIds: Dispatch<SetStateAction<Set<string>>>;
    setSearchText: Dispatch<SetStateAction<string>>;
    setSearchMode: Dispatch<SetStateAction<boolean>>;
    setSearchResults: Dispatch<SetStateAction<KnowledgeFile[]>>;
    setSearchLoading: Dispatch<SetStateAction<boolean>>;
    setSelectedFile: Dispatch<SetStateAction<KnowledgeFile | null>>;
    onNavigateFolder: (folderId?: string, folderName?: string) => void | Promise<void>;
    onRestoreComplete?: (targetKey: string) => void;
}

const getQueryValue = (searchParams: URLSearchParams, keys: string[]) => {
    for (const key of keys) {
        const value = searchParams.get(key)?.trim();
        if (value) return value;
    }
    return "";
};

export const resolvePortalDeepLinkTarget = (searchParams: URLSearchParams): PortalDeepLinkTarget | null => {
    const spaceId = getQueryValue(searchParams, ["spaceId", "knowledgeId", "knowledge_id"]);
    if (!spaceId) return null;
    const folderId = getQueryValue(searchParams, ["folderId", "folder_id"]);
    const folderName = getQueryValue(searchParams, ["folderName", "folder_name"]);
    const fileId = getQueryValue(searchParams, ["fileId", "documentId", "document_id"]);
    const fileName = getQueryValue(searchParams, ["name", "fileName", "documentName", "document_name"]);
    const openNonce = getQueryValue(searchParams, ["openNonce", "open_nonce"]);
    return {
        spaceId,
        folderId,
        folderName,
        fileId,
        fileName,
        openNonce,
        // openNonce lets postMessage re-open the same file after the preview was closed.
        key: `${spaceId}:${folderId}:${folderName}:${fileId}:${fileName}:${openNonce}`,
    };
};

const resolveFileTypeFromName = (name: string): FileType => {
    const ext = name.split(".").pop()?.toLowerCase();
    if (ext && Object.values(FileType).includes(ext as FileType) && ext !== FileType.FOLDER) {
        return ext as FileType;
    }
    return FileType.OTHER;
};

const createDeepLinkedFile = (target: PortalDeepLinkTarget, fileId: string): KnowledgeFile => {
    const name = target.fileName || `文件 ${target.fileId}`;
    return {
        id: fileId,
        name,
        type: resolveFileTypeFromName(name),
        // Preview APIs expect a successful parse status; omit/waiting can block the viewer.
        status: FileStatus.SUCCESS,
        tags: [],
        path: name,
        spaceId: target.spaceId,
        createdAt: "",
        updatedAt: "",
    };
};

export function usePortalDeepLink({
    searchParams,
    activeSpace,
    activeSpaceIdRef,
    selectableSpaces,
    displayedFiles,
    statusFilterNumbers,
    setActiveSpace,
    setCurrentFolderId,
    setSelectedFileIds,
    setSelectedFolderIds,
    setSearchText,
    setSearchMode,
    setSearchResults,
    setSearchLoading,
    setSelectedFile,
    onNavigateFolder,
    onRestoreComplete,
}: UsePortalDeepLinkParams) {
    const deepLinkTarget = useMemo(
        () => resolvePortalDeepLinkTarget(searchParams),
        [searchParams],
    );
    const deepLinkSpaceAppliedRef = useRef<string | null>(null);
    const deepLinkFolderAppliedRef = useRef<string | null>(null);
    const deepLinkHandledRef = useRef<string | null>(null);
    /** Prevents restarting search when displayedFiles churns during tree load. */
    const deepLinkFileSearchKeyRef = useRef<string | null>(null);

    useEffect(() => {
        deepLinkSpaceAppliedRef.current = null;
        deepLinkFolderAppliedRef.current = null;
        deepLinkHandledRef.current = null;
        deepLinkFileSearchKeyRef.current = null;
    }, [deepLinkTarget?.key]);

    useEffect(() => {
        if (!deepLinkTarget || deepLinkSpaceAppliedRef.current === deepLinkTarget.key) return;
        const targetSpace = selectableSpaces.find((space) => String(space.id) === deepLinkTarget.spaceId);
        if (!targetSpace) return;
        deepLinkSpaceAppliedRef.current = deepLinkTarget.key;
        if (String(activeSpace?.id) !== deepLinkTarget.spaceId) {
            setActiveSpace(targetSpace);
        }
    }, [activeSpace?.id, deepLinkTarget, selectableSpaces, setActiveSpace]);

    useEffect(() => {
        if (!deepLinkTarget?.folderId || !activeSpace || String(activeSpace.id) !== deepLinkTarget.spaceId) return;
        if (deepLinkFolderAppliedRef.current === deepLinkTarget.key) return;
        deepLinkFolderAppliedRef.current = deepLinkTarget.key;
        setSelectedFile(null);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
        setSearchText("");
        setSearchLoading(false);
        setSearchMode(false);
        setSearchResults([]);
        void Promise.resolve(onNavigateFolder(deepLinkTarget.folderId, deepLinkTarget.folderName))
            .finally(() => {
                // Folder-only links must clear the restore overlay even if this effect
                // was cleaned up (onNavigateFolder identity often churns after tree load).
                if (!deepLinkTarget.fileId) {
                    onRestoreComplete?.(deepLinkTarget.key);
                }
            });
    }, [
        activeSpace,
        deepLinkTarget,
        onNavigateFolder,
        onRestoreComplete,
        setSearchLoading,
        setSearchMode,
        setSearchResults,
        setSearchText,
        setSelectedFile,
        setSelectedFileIds,
        setSelectedFolderIds,
    ]);

    /** Select preview without entering searchMode — return-to-list must show the folder tree. */
    const openDeepLinkedFile = (
        target: PortalDeepLinkTarget,
        spaceId: string,
        file: KnowledgeFile,
    ) => {
        if (String(activeSpaceIdRef.current) !== String(spaceId)) return false;
        if (deepLinkHandledRef.current === target.key) return true;
        setCurrentFolderId(target.folderId || undefined);
        setSelectedFileIds(new Set());
        setSelectedFolderIds(new Set());
        setSearchText("");
        setSearchLoading(false);
        setSearchMode(false);
        setSearchResults([]);
        setSelectedFile(file);
        deepLinkHandledRef.current = target.key;
        // Workbench clears the loading overlay after selectedFile matches (and preview settles).
        return true;
    };

    // Fast path: open when the target row is already in the current list.
    useEffect(() => {
        if (!deepLinkTarget?.fileId || !activeSpace || String(activeSpace.id) !== deepLinkTarget.spaceId) return;
        if (deepLinkTarget.folderId && deepLinkFolderAppliedRef.current !== deepLinkTarget.key) return;
        if (deepLinkHandledRef.current === deepLinkTarget.key) return;

        const existingFile = displayedFiles.find((file) => (
            String(file.id) === deepLinkTarget.fileId
            && String(file.spaceId || activeSpace.id) === deepLinkTarget.spaceId
            && !isFolder(file)
        ));
        if (!existingFile) return;
        openDeepLinkedFile(deepLinkTarget, String(activeSpace.id), existingFile);
    }, [
        activeSpace,
        deepLinkTarget,
        displayedFiles,
        setCurrentFolderId,
        setSearchLoading,
        setSearchMode,
        setSearchResults,
        setSearchText,
        setSelectedFile,
        setSelectedFileIds,
        setSelectedFolderIds,
        activeSpaceIdRef,
    ]);

    // Slow path: search once per deep-link key. Do NOT depend on displayedFiles — tree
    // updates used to cancel in-flight search and leave the space list visible without a file.
    useEffect(() => {
        if (!deepLinkTarget?.fileId || !activeSpace || String(activeSpace.id) !== deepLinkTarget.spaceId) return;
        if (deepLinkTarget.folderId && deepLinkFolderAppliedRef.current !== deepLinkTarget.key) return;
        if (deepLinkHandledRef.current === deepLinkTarget.key) return;
        if (deepLinkFileSearchKeyRef.current === deepLinkTarget.key) return;

        deepLinkFileSearchKeyRef.current = deepLinkTarget.key;
        const target = deepLinkTarget;
        const spaceId = String(activeSpace.id);
        const fallbackFile = createDeepLinkedFile(target, target.fileId);
        const keyword = target.fileName || target.fileId;
        let cancelled = false;
        setSearchLoading(true);
        searchSpaceChildrenApi({
            space_id: target.spaceId,
            parent_id: target.folderId || undefined,
            keyword,
            page: 1,
            page_size: TREE_PAGE_SIZE,
            file_status: statusFilterNumbers,
        }).then((res) => {
            if (cancelled) return;
            const matchedFile = res.data.find((file) => (
                String(file.id) === target.fileId
                && !isFolder(file)
            ));
            // Search is metadata lookup only — do not leave the workbench in searchMode.
            openDeepLinkedFile(target, spaceId, matchedFile ?? fallbackFile);
        }).catch(() => {
            if (cancelled) return;
            openDeepLinkedFile(target, spaceId, fallbackFile);
        }).finally(() => {
            if (!cancelled && String(activeSpaceIdRef.current) === spaceId) {
                setSearchLoading(false);
            }
        });

        return () => {
            // Cancel only when this effect re-runs for a new key/space/filters (deps below).
            cancelled = true;
            if (deepLinkFileSearchKeyRef.current === target.key) {
                deepLinkFileSearchKeyRef.current = null;
            }
        };
    }, [
        activeSpace?.id,
        deepLinkTarget?.key,
        deepLinkTarget?.fileId,
        deepLinkTarget?.folderId,
        deepLinkTarget?.fileName,
        deepLinkTarget?.spaceId,
        statusFilterNumbers,
        activeSpaceIdRef,
        setCurrentFolderId,
        setSearchLoading,
        setSearchMode,
        setSearchResults,
        setSearchText,
        setSelectedFile,
        setSelectedFileIds,
        setSelectedFolderIds,
    ]);
}
