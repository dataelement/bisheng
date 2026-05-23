import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
    addFilesApi,
    createFolderApi,
    getSimilarCandidatesApi,
    linkAsNewVersionApi,
    listKnowledgeFolders,
    uploadFileToServerApi,
    type FileStatus,
    type KnowledgeSpace,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import {
    ALLOWED_EXTENSIONS,
    DEFAULT_MAX_FILE_SIZE_MB,
    MAX_FOLDER_UPLOAD_COUNT,
    filterFolderUploadFiles,
    getRootFolderName,
    isHiddenName,
} from "../../knowledgeUtils";
import type {
    PortalFileTreeNode,
    PortalUploadFileItem,
    PortalUploadFolderNode,
    PortalUploadReviewRow,
    PortalUploadStep,
} from "../types";
import {
    createUploadFolderNode,
    flattenUploadFolders,
    updateUploadFolderNode,
} from "../utils";

interface UsePortalUploadDialogParams {
    activeSpace: KnowledgeSpace | null;
    setActiveSpace: Dispatch<SetStateAction<KnowledgeSpace | null>>;
    uploadTargetSpace: KnowledgeSpace | null;
    canUploadInPortal: boolean;
    currentFolderId?: string;
    currentFolderNode: PortalFileTreeNode | null;
    currentPath: Array<{ id?: string; name: string }>;
    statusFilterNumbers: number[];
    reloadFiles: () => Promise<void>;
    showToast: (toast: { message: string; severity: NotificationSeverity }) => void;
}

export function usePortalUploadDialog({
    activeSpace,
    setActiveSpace,
    uploadTargetSpace,
    canUploadInPortal,
    currentFolderId,
    currentFolderNode,
    currentPath,
    statusFilterNumbers,
    reloadFiles,
    showToast,
}: UsePortalUploadDialogParams) {
    const uploadInputRef = useRef<HTMLInputElement>(null);
    const uploadFolderInputRef = useRef<HTMLInputElement>(null);
    const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
    const [uploadStep, setUploadStep] = useState<PortalUploadStep>("select");
    const [uploadFiles, setUploadFiles] = useState<PortalUploadFileItem[]>([]);
    const [uploadLocalFolderName, setUploadLocalFolderName] = useState<string | null>(null);
    const [uploadFolderId, setUploadFolderId] = useState<string | null>(null);
    const [uploadFolderName, setUploadFolderName] = useState("根目录");
    const [uploadFolderNodes, setUploadFolderNodes] = useState<PortalUploadFolderNode[]>([]);
    const [uploadFolderLoading, setUploadFolderLoading] = useState(false);
    const [uploadSubmitting, setUploadSubmitting] = useState(false);
    const [uploadImporting, setUploadImporting] = useState(false);
    const [uploadReviewRows, setUploadReviewRows] = useState<PortalUploadReviewRow[]>([]);

    const uploadFolderOptions = useMemo(
        () => {
            const folders = flattenUploadFolders(uploadFolderNodes);
            const options: Array<{ id: string | null; name: string }> = [{ id: null, name: "根目录" }];
            const seen = new Set([""]);
            const appendOption = (id: string | null, name: string) => {
                const key = id ?? "";
                if (seen.has(key)) return;
                seen.add(key);
                options.push({ id, name });
            };
            if (uploadFolderId !== null) {
                appendOption(uploadFolderId, uploadFolderName);
            }
            uploadReviewRows.forEach((row) => {
                if (row.recommendedFolderId !== null) {
                    appendOption(row.recommendedFolderId, row.recommendedFolderName);
                }
                if (row.storageFolderId !== null) {
                    appendOption(row.storageFolderId, row.storageFolderName);
                }
            });
            folders.forEach((folder) => appendOption(folder.id, folder.name));
            return options;
        },
        [uploadFolderId, uploadFolderName, uploadFolderNodes, uploadReviewRows],
    );

    const resetUploadDialog = useCallback(() => {
        setUploadDialogOpen(false);
        setUploadStep("select");
        setUploadFiles([]);
        setUploadLocalFolderName(null);
        setUploadFolderId(null);
        setUploadFolderName("根目录");
        setUploadFolderNodes([]);
        setUploadFolderLoading(false);
        setUploadSubmitting(false);
        setUploadImporting(false);
        setUploadReviewRows([]);
        if (uploadInputRef.current) {
            uploadInputRef.current.value = "";
        }
        if (uploadFolderInputRef.current) {
            uploadFolderInputRef.current.value = "";
        }
    }, []);

    const handleOpenUploadDialog = useCallback(() => {
        if (!uploadTargetSpace || !canUploadInPortal) return;
        if (!activeSpace) {
            setActiveSpace(uploadTargetSpace);
        }
        const currentFolderName = currentFolderId
            ? currentPath[currentPath.length - 1]?.name || currentFolderNode?.file.name || "根目录"
            : "根目录";
        setUploadStep("select");
        setUploadFiles([]);
        setUploadLocalFolderName(null);
        setUploadReviewRows([]);
        setUploadFolderId(currentFolderId ?? null);
        setUploadFolderName(currentFolderName);
        setUploadDialogOpen(true);
    }, [activeSpace, canUploadInPortal, currentFolderId, currentFolderNode?.file.name, currentPath, setActiveSpace, uploadTargetSpace]);

    useEffect(() => {
        if (!uploadDialogOpen || !activeSpace) return;
        let cancelled = false;
        setUploadFolderLoading(true);
        listKnowledgeFolders({
            space_id: activeSpace.id,
            parent_id: null,
            file_status: statusFilterNumbers,
        })
            .then(({ items }) => {
                if (cancelled) return;
                setUploadFolderNodes(items.map(createUploadFolderNode));
            })
            .catch(() => {
                if (cancelled) return;
                setUploadFolderNodes([]);
                showToast({ message: "目录加载失败", severity: NotificationSeverity.ERROR });
            })
            .finally(() => {
                if (!cancelled) setUploadFolderLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [activeSpace, showToast, statusFilterNumbers, uploadDialogOpen]);

    const handleAddUploadFiles = useCallback((files?: FileList | File[]) => {
        const nextFiles = Array.from(files ?? []);
        if (!nextFiles.length) return;
        setUploadLocalFolderName(null);
        setUploadFiles((prev) => [
            ...prev.filter((item) => item.source === "file"),
            ...nextFiles.map((file) => ({
                id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
                file,
                source: "file" as const,
            })),
        ]);
        setUploadStep("select");
        setUploadReviewRows([]);
    }, []);

    const handleAddUploadFolder = useCallback((files?: FileList | File[]) => {
        const allFiles = Array.from(files ?? []);
        if (!allFiles.length) return;

        const rootNames = Array.from(new Set(
            allFiles
                .map((file) => getRootFolderName(file.webkitRelativePath || ""))
                .filter(Boolean),
        ));
        const rootName = rootNames[0] || "";
        if (!rootName) {
            showToast({ message: "请选择一个有效文件夹", severity: NotificationSeverity.WARNING });
            return;
        }
        if (isHiddenName(rootName)) {
            showToast({ message: "不支持上传隐藏文件夹", severity: NotificationSeverity.WARNING });
            return;
        }
        if (allFiles.length > MAX_FOLDER_UPLOAD_COUNT) {
            showToast({
                message: `文件夹上传最多支持 ${MAX_FOLDER_UPLOAD_COUNT} 个文件`,
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        if (rootNames.length > 1) {
            showToast({ message: "一次仅支持上传一个文件夹，已保留第一个文件夹", severity: NotificationSeverity.INFO });
        }

        const filesInRoot = allFiles.filter((file) => getRootFolderName(file.webkitRelativePath || "") === rootName);
        const validFiles = filterFolderUploadFiles(filesInRoot, {
            allowedExtensions: ALLOWED_EXTENSIONS,
            maxSizeMB: DEFAULT_MAX_FILE_SIZE_MB,
        });
        if (!validFiles.length) {
            showToast({ message: "文件夹根目录下没有可上传的支持文件", severity: NotificationSeverity.WARNING });
            return;
        }

        setUploadLocalFolderName(rootName);
        setUploadFiles(validFiles.map((file) => ({
            id: `${rootName}-${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
            file,
            source: "folder" as const,
        })));
        setUploadStep("select");
        setUploadReviewRows([]);
    }, [showToast]);

    const handleRemoveUploadFile = useCallback((fileId: string) => {
        setUploadFiles((prev) => {
            const next = prev.filter((item) => item.id !== fileId);
            if (!next.length) {
                setUploadLocalFolderName(null);
            }
            return next;
        });
        setUploadReviewRows([]);
    }, []);

    const handleSelectUploadFolder = useCallback((folderId: string | null, folderName: string) => {
        setUploadFolderId(folderId);
        setUploadFolderName(folderName);
    }, []);

    const handleToggleUploadFolder = useCallback(async (node: PortalUploadFolderNode) => {
        const spaceId = activeSpace?.id;
        if (!spaceId) return;
        if (node.expanded) {
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                expanded: false,
            })));
            return;
        }
        if (node.loaded) {
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                expanded: true,
            })));
            return;
        }
        setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
            ...item,
            expanded: true,
            loading: true,
        })));
        const parentId = Number(node.id);
        try {
            const { items } = await listKnowledgeFolders({
                space_id: spaceId,
                parent_id: Number.isFinite(parentId) ? parentId : node.id,
                file_status: statusFilterNumbers,
            });
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                children: items.map(createUploadFolderNode),
                expanded: true,
                loaded: true,
                loading: false,
            })));
        } catch {
            setUploadFolderNodes((prev) => updateUploadFolderNode(prev, node.id, (item) => ({
                ...item,
                expanded: false,
                loading: false,
            })));
            showToast({ message: "目录加载失败", severity: NotificationSeverity.ERROR });
        }
    }, [activeSpace?.id, showToast, statusFilterNumbers]);

    const loadUploadReviewCandidates = useCallback((rows: PortalUploadReviewRow[]) => {
        rows.forEach((row) => {
            const fileId = Number(row.file.id);
            if (!Number.isFinite(fileId)) return;
            void getSimilarCandidatesApi(fileId)
                .then((candidates) => {
                    setUploadReviewRows((prev) => prev.map((item) => item.file.id === row.file.id ? {
                        ...item,
                        candidates,
                        candidatesLoading: false,
                        candidateError: false,
                    } : item));
                })
                .catch(() => {
                    setUploadReviewRows((prev) => prev.map((item) => item.file.id === row.file.id ? {
                        ...item,
                        candidates: [],
                        candidatesLoading: false,
                        candidateError: true,
                    } : item));
                    showToast({ message: `${row.file.name} 版本推荐加载失败`, severity: NotificationSeverity.ERROR });
                });
        });
    }, [showToast]);

    const handleUploadNext = useCallback(async () => {
        if (uploadReviewRows.length) {
            setUploadStep("review");
            return;
        }
        if (!activeSpace) return;
        if (!uploadFiles.length) {
            showToast({ message: "请先选择文件", severity: NotificationSeverity.INFO });
            return;
        }
        setUploadSubmitting(true);
        try {
            if (uploadLocalFolderName) {
                const targetParentId = uploadFolderId === null ? null : Number(uploadFolderId);
                const normalizedParentId = uploadFolderId === null
                    ? null
                    : Number.isFinite(targetParentId)
                        ? targetParentId
                        : uploadFolderId;
                const { items } = await listKnowledgeFolders({
                    space_id: activeSpace.id,
                    parent_id: normalizedParentId,
                });
                if (items.some((item) => item.file_name === uploadLocalFolderName)) {
                    showToast({
                        message: `该位置已存在同名文件夹「${uploadLocalFolderName}」`,
                        severity: NotificationSeverity.WARNING,
                    });
                    return;
                }

                const createdFolder = await createFolderApi(activeSpace.id, {
                    name: uploadLocalFolderName,
                    parent_id: uploadFolderId,
                });
                const createdFolderId = Number(createdFolder.id);
                if (!Number.isFinite(createdFolderId)) {
                    throw new Error("创建文件夹失败");
                }

                const uploadResults = await Promise.all(
                    uploadFiles.map((item) => uploadFileToServerApi(activeSpace.id, item.file, item.file.name)),
                );
                const filePaths = uploadResults.map((item) => item.file_path);
                const registeredFiles = await addFilesApi(activeSpace.id, {
                    file_path: filePaths,
                    parent_id: createdFolderId,
                });
                const createdFolderOptionId = String(createdFolder.id);
                const rows: PortalUploadReviewRow[] = registeredFiles.map((file) => ({
                    file,
                    selected: true,
                    recommendedFolderId: createdFolderOptionId,
                    recommendedFolderName: createdFolder.name,
                    storageFolderId: createdFolderOptionId,
                    storageFolderName: createdFolder.name,
                    candidates: [],
                    candidatesLoading: true,
                    candidateError: false,
                    selectedTargetDocumentId: null,
                }));
                setUploadReviewRows(rows);
                setUploadStep("review");
                loadUploadReviewCandidates(rows);
                return;
            }

            const uploadResults = await Promise.all(
                uploadFiles.map((item) => uploadFileToServerApi(activeSpace.id, item.file)),
            );
            const filePaths = uploadResults.map((item) => item.file_path);
            const parentId = uploadFolderId === null ? null : Number(uploadFolderId);
            const registeredFiles = await addFilesApi(activeSpace.id, {
                file_path: filePaths,
                parent_id: parentId !== null && Number.isFinite(parentId) ? parentId : null,
            });
            const rows: PortalUploadReviewRow[] = registeredFiles.map((file) => ({
                file,
                selected: true,
                recommendedFolderId: uploadFolderId,
                recommendedFolderName: uploadFolderName,
                storageFolderId: uploadFolderId,
                storageFolderName: uploadFolderName,
                candidates: [],
                candidatesLoading: true,
                candidateError: false,
                selectedTargetDocumentId: null,
            }));
            setUploadReviewRows(rows);
            setUploadStep("review");
            loadUploadReviewCandidates(rows);
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "上传失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            setUploadSubmitting(false);
        }
    }, [activeSpace, loadUploadReviewCandidates, showToast, uploadFiles, uploadFolderId, uploadFolderName, uploadLocalFolderName, uploadReviewRows.length]);

    const handleStartUploadImport = useCallback(async () => {
        const rows = uploadReviewRows.filter((row) => row.selected);
        if (!rows.length) {
            showToast({ message: "请至少选择一个文件", severity: NotificationSeverity.INFO });
            return;
        }
        setUploadImporting(true);
        try {
            for (const row of rows) {
                if (!row.selectedTargetDocumentId) continue;
                const fileId = Number(row.file.id);
                if (!Number.isFinite(fileId)) continue;
                await linkAsNewVersionApi({
                    knowledge_file_id: fileId,
                    target_document_id: row.selectedTargetDocumentId,
                });
            }
            await reloadFiles();
            resetUploadDialog();
            showToast({ message: "导入成功", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "版本关联失败", severity: NotificationSeverity.ERROR });
        } finally {
            setUploadImporting(false);
        }
    }, [reloadFiles, resetUploadDialog, showToast, uploadReviewRows]);

    return {
        uploadInputRef,
        uploadFolderInputRef,
        uploadDialogOpen,
        uploadStep,
        uploadFiles,
        uploadLocalFolderName,
        uploadFolderId,
        uploadFolderName,
        uploadFolderNodes,
        uploadFolderLoading,
        uploadSubmitting,
        uploadImporting,
        uploadReviewRows,
        uploadFolderOptions,
        setUploadDialogOpen,
        setUploadStep,
        setUploadReviewRows,
        resetUploadDialog,
        handleOpenUploadDialog,
        handleAddUploadFiles,
        handleAddUploadFolder,
        handleRemoveUploadFile,
        handleSelectUploadFolder,
        handleToggleUploadFolder,
        handleUploadNext,
        handleStartUploadImport,
    };
}
