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
    return {
        spaceId,
        folderId,
        folderName,
        fileId,
        fileName,
        key: `${spaceId}:${folderId}:${folderName}:${fileId}:${fileName}`,
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

    useEffect(() => {
        deepLinkSpaceAppliedRef.current = null;
        deepLinkFolderAppliedRef.current = null;
        deepLinkHandledRef.current = null;
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
        let cancelled = false;
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
                if (!cancelled && !deepLinkTarget.fileId) {
                    onRestoreComplete?.(deepLinkTarget.key);
                }
            });
        return () => {
            cancelled = true;
        };
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

    useEffect(() => {
        if (!deepLinkTarget?.fileId || !activeSpace || String(activeSpace.id) !== deepLinkTarget.spaceId) return;
        if (deepLinkTarget.folderId && deepLinkFolderAppliedRef.current !== deepLinkTarget.key) return;
        if (deepLinkHandledRef.current === deepLinkTarget.key) return;

        let cancelled = false;

        const openDeepLinkedFile = (file: KnowledgeFile, searchResults?: KnowledgeFile[]) => {
            if (cancelled || String(activeSpaceIdRef.current) !== String(activeSpace.id)) return false;
            setCurrentFolderId(deepLinkTarget.folderId || undefined);
            setSelectedFileIds(new Set());
            setSelectedFolderIds(new Set());
            setSearchText(deepLinkTarget.fileName || file.name);
            setSearchLoading(false);
            if (searchResults) {
                setSearchMode(true);
                setSearchResults(searchResults);
            }
            setSelectedFile(file);
            deepLinkHandledRef.current = deepLinkTarget.key;
            onRestoreComplete?.(deepLinkTarget.key);
            return true;
        };

        const existingFile = displayedFiles.find((file) => (
            String(file.id) === deepLinkTarget.fileId
            && String(file.spaceId || activeSpace.id) === deepLinkTarget.spaceId
            && !isFolder(file)
        ));
        if (existingFile) {
            openDeepLinkedFile(existingFile);
            return () => {
                cancelled = true;
            };
        }

        const fallbackFile = createDeepLinkedFile(deepLinkTarget, deepLinkTarget.fileId);
        const keyword = deepLinkTarget.fileName || deepLinkTarget.fileId;
        setSearchLoading(true);
        searchSpaceChildrenApi({
            space_id: deepLinkTarget.spaceId,
            parent_id: deepLinkTarget.folderId || undefined,
            keyword,
            page: 1,
            page_size: TREE_PAGE_SIZE,
            file_status: statusFilterNumbers,
        }).then((res) => {
            const matchedFile = res.data.find((file) => (
                String(file.id) === deepLinkTarget.fileId
                && !isFolder(file)
            ));
            const nextResults = matchedFile ? res.data : [fallbackFile];
            openDeepLinkedFile(matchedFile ?? fallbackFile, nextResults);
        }).catch(() => {
            openDeepLinkedFile(fallbackFile, [fallbackFile]);
        }).finally(() => {
            if (!cancelled && String(activeSpaceIdRef.current) === String(activeSpace.id)) {
                setSearchLoading(false);
            }
        });

        return () => {
            cancelled = true;
        };
    }, [
        activeSpace,
        activeSpaceIdRef,
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
        onRestoreComplete,
        statusFilterNumbers,
    ]);
}
