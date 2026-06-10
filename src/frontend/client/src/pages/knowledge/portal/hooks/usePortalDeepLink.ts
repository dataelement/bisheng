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

interface PortalDeepLinkTarget {
    spaceId: string;
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
}

const getQueryValue = (searchParams: URLSearchParams, keys: string[]) => {
    for (const key of keys) {
        const value = searchParams.get(key)?.trim();
        if (value) return value;
    }
    return "";
};

const resolvePortalDeepLinkTarget = (searchParams: URLSearchParams): PortalDeepLinkTarget | null => {
    const spaceId = getQueryValue(searchParams, ["spaceId", "knowledgeId", "knowledge_id"]);
    const fileId = getQueryValue(searchParams, ["fileId", "documentId", "document_id"]);
    if (!spaceId || !fileId) return null;
    const fileName = getQueryValue(searchParams, ["name", "fileName", "documentName", "document_name"]);
    return {
        spaceId,
        fileId,
        fileName,
        key: `${spaceId}:${fileId}:${fileName}`,
    };
};

const resolveFileTypeFromName = (name: string): FileType => {
    const ext = name.split(".").pop()?.toLowerCase();
    if (ext && Object.values(FileType).includes(ext as FileType) && ext !== FileType.FOLDER) {
        return ext as FileType;
    }
    return FileType.OTHER;
};

const createDeepLinkedFile = (target: PortalDeepLinkTarget): KnowledgeFile => {
    const name = target.fileName || `文件 ${target.fileId}`;
    return {
        id: target.fileId,
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
}: UsePortalDeepLinkParams) {
    const deepLinkTarget = useMemo(
        () => resolvePortalDeepLinkTarget(searchParams),
        [searchParams],
    );
    const deepLinkSpaceAppliedRef = useRef<string | null>(null);
    const deepLinkHandledRef = useRef<string | null>(null);

    useEffect(() => {
        deepLinkSpaceAppliedRef.current = null;
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
        if (!deepLinkTarget || !activeSpace || String(activeSpace.id) !== deepLinkTarget.spaceId) return;
        if (deepLinkHandledRef.current === deepLinkTarget.key) return;

        let cancelled = false;

        const openDeepLinkedFile = (file: KnowledgeFile, searchResults?: KnowledgeFile[]) => {
            if (cancelled || String(activeSpaceIdRef.current) !== String(activeSpace.id)) return false;
            setCurrentFolderId(undefined);
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

        const fallbackFile = createDeepLinkedFile(deepLinkTarget);
        const keyword = deepLinkTarget.fileName || deepLinkTarget.fileId;
        setSearchLoading(true);
        searchSpaceChildrenApi({
            space_id: deepLinkTarget.spaceId,
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
        statusFilterNumbers,
    ]);
}
