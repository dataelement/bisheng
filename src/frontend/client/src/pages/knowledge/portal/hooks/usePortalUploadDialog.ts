import { useCallback, useEffect, useMemo, useRef, useState, type Dispatch, type SetStateAction } from "react";
import {
    addFilesApi,
    createFolderApi,
    getSimilarCandidatesApi,
    getSpaceTagsApi,
    linkAsNewVersionApi,
    listKnowledgeFolders,
    recommendUploadFoldersApi,
    retryDuplicateFilesApi,
    uploadFileToServerApi,
    checkSensitiveWordsApi,
    type KnowledgeSpace,
    type KnowledgeFile,
    type UploadFileRegistrationMetadata,
    type UploadFolderRecommendationItem,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import {
    DEFAULT_MAX_FILE_SIZE_MB,
    DEFAULT_MEDIA_MAX_FILE_SIZE_MB,
    MAX_FOLDER_UPLOAD_COUNT,
    filterNestedFolderUploadFiles,
    extractSortedDirPaths,
    getAllowedExtensions,
    getFileInputAccept,
    getMaxFileSizeBytesForFile,
    getMaxFileSizeMBForFile,
    getRootFolderName,
    isHiddenName,
    type UploadSizeLimits,
} from "../../knowledgeUtils";
import { DEFAULT_PORTAL_FILE_CATEGORY_GROUPS } from "../constants";
import type {
    PortalFileCategoryGroupOption,
    PortalFileSubcategoryOption,
    PortalFileTreeNode,
    PortalUploadFileItem,
    PortalUploadFolderNode,
    PortalUploadFolderSelection,
    PortalUploadReviewRow,
    PortalUploadStep,
} from "../types";
import {
    createUploadFolderNode,
    flattenUploadFolders,
    updateUploadFolderNode,
} from "../utils";
import {
    extractDuplicateFileEntries,
    type DuplicateFileEntry,
} from "../../hooks/duplicateFiles";
import {
    buildPortalUploadMetadataPayload,
    buildUploadTagOptions,
    EMPTY_PORTAL_UPLOAD_METADATA,
    type BusinessDomainOptionItem,
    type PortalUploadMetadataPayload,
    type PortalUploadTagOption,
} from "../uploadMetadata";

interface UsePortalUploadDialogParams {
    activeSpace: KnowledgeSpace | null;
    setActiveSpace: Dispatch<SetStateAction<KnowledgeSpace | null>>;
    uploadTargetSpace: KnowledgeSpace | null;
    canUploadInPortal: boolean;
    currentFolderId?: string;
    currentFolderNode: PortalFileTreeNode | null;
    currentPath: Array<{ id?: string; name: string }>;
    statusFilterNumbers: number[];
    fileCategoryGroups?: PortalFileCategoryGroupOption[];
    businessDomainOptions?: BusinessDomainOptionItem[];
    enableEtl4lm?: boolean;
    uploadSizeLimits?: UploadSizeLimits;
    /** @deprecated Use uploadSizeLimits */
    maxFileSizeMB?: number;
    reloadFiles: () => Promise<void>;
    onUploaded?: () => void;
    showToast: (toast: { message: string; severity: NotificationSeverity }) => void;
}

export function usePortalUploadDialog({
    activeSpace,
    setActiveSpace,
    uploadTargetSpace,
    canUploadInPortal,
    statusFilterNumbers,
    fileCategoryGroups = DEFAULT_PORTAL_FILE_CATEGORY_GROUPS,
    businessDomainOptions = [],
    enableEtl4lm = true,
    uploadSizeLimits,
    maxFileSizeMB = DEFAULT_MAX_FILE_SIZE_MB,
    reloadFiles,
    onUploaded,
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
    const [uploadFolderSelection, setUploadFolderSelection] = useState<PortalUploadFolderSelection>({ mode: "ai" });
    const [uploadFolderNodes, setUploadFolderNodes] = useState<PortalUploadFolderNode[]>([]);
    const [uploadFolderLoading, setUploadFolderLoading] = useState(false);
    const [uploadSubmitting, setUploadSubmitting] = useState(false);
    // Re-entry guard: flips synchronously so rapid double-clicks on the upload
    // button can't launch the pre-upload check + upload flow more than once.
    const uploadSubmittingRef = useRef(false);
    const [uploadImporting, setUploadImporting] = useState(false);
    const [uploadReviewRows, setUploadReviewRows] = useState<PortalUploadReviewRow[]>([]);
    const [duplicateFiles, setDuplicateFiles] = useState<DuplicateFileEntry[]>([]);
    const [duplicateOverwriting, setDuplicateOverwriting] = useState(false);
    // Files skipped during upload because they tripped the sensitive-word filter.
    // Non-empty drives the post-upload notice dialog listing them.
    const [sensitiveWordFiles, setSensitiveWordFiles] = useState<string[]>([]);
    const [duplicateFileCategoryCode, setDuplicateFileCategoryCode] = useState<string | undefined>();
    const [duplicateUploadMetadataPayload, setDuplicateUploadMetadataPayload] = useState<PortalUploadMetadataPayload>({});
    const [fileSubcategoryCode, setFileSubcategoryCode] = useState("");
    const [businessDomainCode, setBusinessDomainCode] = useState(EMPTY_PORTAL_UPLOAD_METADATA.businessDomainCode);
    const [selectedUploadTagValues, setSelectedUploadTagValues] = useState<string[]>([]);
    const [uploadTagOptions, setUploadTagOptions] = useState<PortalUploadTagOption[]>([]);
    const [uploadTagLoading, setUploadTagLoading] = useState(false);
    const allowedExtensions = useMemo(() => getAllowedExtensions(enableEtl4lm), [enableEtl4lm]);
    const fileInputAccept = useMemo(() => getFileInputAccept(enableEtl4lm), [enableEtl4lm]);
    const supportedFormatsLabel = useMemo(() => allowedExtensions.join("、"), [allowedExtensions]);
    const resolvedUploadSizeLimits = useMemo(
        () => uploadSizeLimits ?? {
            defaultMaxMB: maxFileSizeMB,
            mediaMaxMB: DEFAULT_MEDIA_MAX_FILE_SIZE_MB,
        },
        [uploadSizeLimits, maxFileSizeMB],
    );
    const displayMaxFileSizeMB = resolvedUploadSizeLimits.defaultMaxMB;

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
        setUploadFolderSelection({ mode: "ai" });
        setUploadFolderNodes([]);
        setUploadFolderLoading(false);
        uploadSubmittingRef.current = false;
        setUploadSubmitting(false);
        setUploadImporting(false);
        setUploadReviewRows([]);
        setDuplicateFiles([]);
        setDuplicateFileCategoryCode(undefined);
        setDuplicateUploadMetadataPayload({});
        setFileSubcategoryCode("");
        setBusinessDomainCode("");
        setSelectedUploadTagValues([]);
        setUploadTagOptions([]);
        setUploadTagLoading(false);
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
        setUploadStep("select");
        setUploadFiles([]);
        setUploadLocalFolderName(null);
        setUploadReviewRows([]);
        setDuplicateFiles([]);
        setDuplicateFileCategoryCode(undefined);
        setDuplicateUploadMetadataPayload({});
        setFileSubcategoryCode("");
        setBusinessDomainCode("");
        setSelectedUploadTagValues([]);
        setUploadFolderId(null);
        setUploadFolderName("根目录");
        setUploadFolderSelection({ mode: "ai" });
        setUploadDialogOpen(true);
    }, [activeSpace, canUploadInPortal, setActiveSpace, uploadTargetSpace]);

    useEffect(() => {
        if (!fileSubcategoryCode) return;
        if (!fileCategoryGroups.some((group) => group.children.some((option) => option.code === fileSubcategoryCode))) {
            setFileSubcategoryCode("");
        }
    }, [fileSubcategoryCode, fileCategoryGroups]);

    const selectedFileSubcategory = useMemo<PortalFileSubcategoryOption | null>(() => {
        if (!fileSubcategoryCode) return null;
        for (const group of fileCategoryGroups) {
            const option = group.children.find((child) => child.code === fileSubcategoryCode);
            if (option) return option;
        }
        return null;
    }, [fileCategoryGroups, fileSubcategoryCode]);

    useEffect(() => {
        if (!businessDomainCode) return;
        if (!businessDomainOptions.some((option) => option.code === businessDomainCode)) {
            setBusinessDomainCode("");
        }
    }, [businessDomainCode, businessDomainOptions]);

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

    const validateUploadFiles = useCallback((files: File[]) => {
        const unsupportedFiles: string[] = [];
        const oversizedFiles: string[] = [];
        const validFiles = files.filter((file) => {
            if (file.size > getMaxFileSizeBytesForFile(file.name, resolvedUploadSizeLimits)) {
                oversizedFiles.push(file.name);
                return false;
            }
            const ext = file.name.split(".").pop()?.toLowerCase();
            if (!ext || !allowedExtensions.includes(ext)) {
                unsupportedFiles.push(file.name);
                return false;
            }
            return true;
        });

        if (unsupportedFiles.length) {
            showToast({
                message: `不支持的文件格式：${unsupportedFiles.join("、")}`,
                severity: NotificationSeverity.WARNING,
            });
        }
        if (oversizedFiles.length) {
            showToast({
                message: `文件大小超过 ${displayMaxFileSizeMB}MB：${oversizedFiles.join("、")}`,
                severity: NotificationSeverity.WARNING,
            });
        }
        return validFiles;
    }, [allowedExtensions, resolvedUploadSizeLimits, displayMaxFileSizeMB, showToast]);

    const handleAddUploadFiles = useCallback((files?: FileList | File[]) => {
        const nextFiles = Array.from(files ?? []);
        if (!nextFiles.length) return;
        const validFiles = validateUploadFiles(nextFiles);
        if (!validFiles.length) return;
        setUploadLocalFolderName(null);
        setUploadFiles((prev) => [
            ...prev.filter((item) => item.source === "file"),
            ...validFiles.map((file) => ({
                id: `${file.name}-${file.size}-${file.lastModified}-${Math.random().toString(36).slice(2)}`,
                file,
                source: "file" as const,
            })),
        ]);
        setUploadStep("select");
        setUploadReviewRows([]);
    }, [validateUploadFiles]);

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
        const validFiles = filterNestedFolderUploadFiles(filesInRoot, {
            allowedExtensions,
            limits: resolvedUploadSizeLimits,
        });
        if (!validFiles.length) {
            showToast({ message: "文件夹中没有可上传的支持文件", severity: NotificationSeverity.WARNING });
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
    }, [allowedExtensions, resolvedUploadSizeLimits, showToast]);

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
        setUploadFolderSelection({ mode: "manual", folderId, folderName });
    }, []);

    const handleUseAiUploadFolder = useCallback(() => {
        setUploadFolderId(null);
        setUploadFolderName("根目录");
        setUploadFolderSelection({ mode: "ai" });
    }, []);

    const handleSelectFileCategory = useCallback((code: string) => {
        setFileSubcategoryCode(code);
    }, []);

    const handleSelectBusinessDomain = useCallback((code: string) => {
        setBusinessDomainCode(code);
    }, []);

    const handleToggleUploadTag = useCallback((value: string) => {
        setSelectedUploadTagValues((prev) => (
            prev.includes(value)
                ? prev.filter((item) => item !== value)
                : [...prev, value]
        ));
    }, []);

    const handleClearUploadTags = useCallback(() => {
        setSelectedUploadTagValues([]);
    }, []);

    useEffect(() => {
        if (!uploadDialogOpen || !activeSpace?.id) {
            return;
        }
        let cancelled = false;
        const loadUploadTagOptions = async () => {
            setUploadTagLoading(true);
            try {
                const existingTags = await getSpaceTagsApi(activeSpace.id);
                if (!cancelled) {
                    setUploadTagOptions(buildUploadTagOptions(existingTags, []));
                }
            } catch {
                if (!cancelled) {
                    setUploadTagOptions([]);
                }
            } finally {
                if (!cancelled) {
                    setUploadTagLoading(false);
                }
            }
        };
        void loadUploadTagOptions().catch(() => {
            if (!cancelled) {
                setUploadTagOptions([]);
                setUploadTagLoading(false);
            }
        });
        return () => {
            cancelled = true;
        };
    }, [activeSpace?.id, uploadDialogOpen]);

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

    const getVisibleRegisteredFiles = useCallback((registeredFiles: Awaited<ReturnType<typeof addFilesApi>>) => {
        const dupes = extractDuplicateFileEntries(registeredFiles);
        setDuplicateFiles(dupes);
        const duplicateIds = new Set(dupes.map((file) => String(file.fileId)));
        return registeredFiles.filter((file) => !duplicateIds.has(String(file.id)));
    }, []);

    const finishUploadedFiles = useCallback(async (
        registeredFiles: KnowledgeFile[],
        uploadMetadataPayload: PortalUploadMetadataPayload,
    ) => {
        const visibleRegisteredFiles = getVisibleRegisteredFiles(registeredFiles);
        const hasDuplicateFiles = visibleRegisteredFiles.length !== registeredFiles.length;
        if (hasDuplicateFiles) {
            setDuplicateFileCategoryCode(uploadMetadataPayload.file_category_code);
            setDuplicateUploadMetadataPayload(uploadMetadataPayload);
            if (visibleRegisteredFiles.length) {
                await reloadFiles();
            }
            setUploadDialogOpen(false);
            setUploadStep("select");
            setUploadFiles([]);
            setUploadLocalFolderName(null);
            setUploadFolderId(null);
            setUploadFolderName("根目录");
            setUploadFolderSelection({ mode: "ai" });
            setUploadReviewRows([]);
            setFileSubcategoryCode("");
            setBusinessDomainCode("");
            setSelectedUploadTagValues([]);
            return;
        }
        setDuplicateFileCategoryCode(undefined);
        setDuplicateUploadMetadataPayload({});
        await reloadFiles();
        setUploadDialogOpen(false);
        setUploadStep("select");
        setUploadFiles([]);
        setUploadLocalFolderName(null);
        setUploadFolderId(null);
        setUploadFolderName("根目录");
        setUploadFolderSelection({ mode: "ai" });
        setUploadReviewRows([]);
        setFileSubcategoryCode("");
        setBusinessDomainCode("");
        setSelectedUploadTagValues([]);
        onUploaded?.();
        showToast({ message: "上传成功", severity: NotificationSeverity.SUCCESS });
    }, [getVisibleRegisteredFiles, onUploaded, reloadFiles, showToast]);

    const resolveManualParentId = useCallback(() => {
        if (uploadFolderSelection.mode !== "manual") return null;
        const parsed = uploadFolderSelection.folderId === null ? null : Number(uploadFolderSelection.folderId);
        return parsed !== null && Number.isFinite(parsed) ? parsed : null;
    }, [uploadFolderSelection]);

    const recommendUploadTargetMap = useCallback(async (
        items: Array<{ id: string; name: string }>,
    ): Promise<Map<string, UploadFolderRecommendationItem>> => {
        if (!activeSpace || uploadFolderSelection.mode === "manual") {
            return new Map();
        }
        const result = await recommendUploadFoldersApi(activeSpace.id, {
            files: items.map((item) => ({
                client_file_id: item.id,
                file_name: item.name,
            })),
        });
        return new Map(result.items.map((item) => [item.clientFileId, item]));
    }, [activeSpace, uploadFolderSelection.mode]);

    const recommendationParentId = useCallback((recommendation?: UploadFolderRecommendationItem) => {
        if (!recommendation?.recommendedFolderId) return null;
        const parsed = Number(recommendation.recommendedFolderId);
        return Number.isFinite(parsed) ? parsed : null;
    }, []);

    const registerUploadedFiles = useCallback(async (
        uploadItems: PortalUploadFileItem[],
        filePaths: string[],
        recommendations: Map<string, UploadFolderRecommendationItem>,
        uploadMetadataPayload: UploadFileRegistrationMetadata,
    ) => {
        const groups = new Map<string, { parentId: number | null; filePaths: string[] }>();
        uploadItems.forEach((item, index) => {
            const parentId = uploadFolderSelection.mode === "manual"
                ? resolveManualParentId()
                : recommendationParentId(recommendations.get(item.id));
            const key = parentId === null ? "root" : String(parentId);
            const group = groups.get(key) ?? { parentId, filePaths: [] };
            group.filePaths.push(filePaths[index]);
            groups.set(key, group);
        });

        const registeredFiles: KnowledgeFile[] = [];
        for (const group of groups.values()) {
            const files = await addFilesApi(activeSpace!.id, {
                file_path: group.filePaths,
                parent_id: group.parentId,
                ...uploadMetadataPayload,
            });
            registeredFiles.push(...files);
        }
        return registeredFiles;
    }, [activeSpace, recommendationParentId, resolveManualParentId, uploadFolderSelection.mode]);

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
        // Guard re-entry and flip the button to its busy state up front, before
        // the (potentially many, network-bound) sensitive-word checks run — so
        // the button disables immediately instead of only after all checks pass.
        if (uploadSubmittingRef.current) return;
        uploadSubmittingRef.current = true;
        setUploadSubmitting(true);
        try {
            const uploadMetadataPayload = buildPortalUploadMetadataPayload(
                { businessDomainCode, selectedTagValues: selectedUploadTagValues },
                selectedFileSubcategory,
            );

            // Pre-upload sensitive-word check. Rather than aborting the whole batch
            // when any file trips the filter, collect the offending files, upload the
            // rest normally, and report the skipped ones to the user at the end.
            const sensitiveFileNames = new Set<string>();

            // Filenames (batch): violated_texts echoes the offending filenames.
            const filenames = uploadFiles.map((item) => item.file.name);
            const filenameCheck = await checkSensitiveWordsApi(activeSpace.id, filenames);
            if (filenameCheck.has_violation) {
                for (const text of filenameCheck.violated_texts) sensitiveFileNames.add(text);
            }

            // Text file content (per file, report by filename). Runs concurrently so
            // N text files cost one round-trip window, not N serialized ones.
            const TEXT_EXTENSIONS = new Set(["txt", "md", "csv", "html", "htm"]);
            const textItems = uploadFiles.filter(
                (item) => TEXT_EXTENSIONS.has(item.file.name.split(".").pop()?.toLowerCase() ?? ""),
            );
            const contentChecks = await Promise.all(
                textItems.map(async (item) => {
                    try {
                        const content = await item.file.text();
                        const contentCheck = await checkSensitiveWordsApi(activeSpace.id, [content]);
                        return contentCheck.has_violation ? item.file.name : null;
                    } catch {
                        // Skip content check on read error
                        return null;
                    }
                }),
            );
            for (const name of contentChecks) {
                if (name !== null) sensitiveFileNames.add(name);
            }

            const sensitiveFileList = Array.from(sensitiveFileNames);
            const filesToUpload = sensitiveFileNames.size
                ? uploadFiles.filter((item) => !sensitiveFileNames.has(item.file.name))
                : uploadFiles;

            // Every selected file tripped the filter — nothing left to upload.
            if (filesToUpload.length === 0) {
                setSensitiveWordFiles(sensitiveFileList);
                return;
            }

            if (uploadLocalFolderName) {
                const recommendations = await recommendUploadTargetMap([
                    { id: `folder:${uploadLocalFolderName}`, name: uploadLocalFolderName },
                ]);
                const recommendedParentId = recommendationParentId(recommendations.get(`folder:${uploadLocalFolderName}`));
                const normalizedParentId = uploadFolderSelection.mode === "manual"
                    ? resolveManualParentId()
                    : recommendedParentId;
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

                // Build nested folder structure (BFS order: parents before children)
                const allValidFiles = filesToUpload.map((item) => item.file);
                const dirPaths = extractSortedDirPaths(allValidFiles);
                const folderIdMap = new Map<string, string>();

                for (const dirPath of dirPaths) {
                    const parts = dirPath.split("/");
                    const name = parts[parts.length - 1];
                    const parentPath = parts.slice(0, -1).join("/");
                    const isRootLevel = parts.length === 1;

                    if (!isRootLevel && !folderIdMap.has(parentPath)) continue;

                    const parentFolderId = isRootLevel
                        ? (normalizedParentId === null ? null : String(normalizedParentId))
                        : (folderIdMap.get(parentPath) ?? null);

                    try {
                        const folder = await createFolderApi(activeSpace.id, { name, parent_id: parentFolderId });
                        folderIdMap.set(dirPath, folder.id);
                    } catch (err: unknown) {
                        if (isRootLevel) throw new Error(`创建文件夹失败: ${err instanceof Error ? err.message : String(err)}`);
                        // Non-root folder failures skip the subtree silently
                    }
                }

                // Group files by their parent directory and upload
                const filesByDir = new Map<string, typeof uploadFiles>();
                for (const item of filesToUpload) {
                    const rel = item.file.webkitRelativePath;
                    const parentPath = rel.split("/").slice(0, -1).join("/");
                    const arr = filesByDir.get(parentPath) ?? [];
                    arr.push(item);
                    filesByDir.set(parentPath, arr);
                }

                const allRegistered: KnowledgeFile[] = [];
                for (const [dirPath, dirItems] of filesByDir) {
                    const parentFolderId = folderIdMap.get(dirPath);
                    if (!parentFolderId) continue;
                    const uploadResults = await Promise.all(
                        dirItems.map((item) => uploadFileToServerApi(activeSpace.id, item.file, item.file.name)),
                    );
                    const filePaths = uploadResults.map((r) => r.file_path);
                    const registered = await addFilesApi(activeSpace.id, {
                        file_path: filePaths,
                        parent_id: Number(parentFolderId),
                        ...uploadMetadataPayload,
                    });
                    allRegistered.push(...registered);
                }
                await finishUploadedFiles(allRegistered, uploadMetadataPayload);
                if (sensitiveFileList.length) setSensitiveWordFiles(sensitiveFileList);
                return;
            }

            const recommendations = await recommendUploadTargetMap(filesToUpload.map((item) => ({
                id: item.id,
                name: item.file.name,
            })));
            const uploadResults = await Promise.all(
                filesToUpload.map((item) => uploadFileToServerApi(activeSpace.id, item.file)),
            );
            const filePaths = uploadResults.map((item) => item.file_path);
            const registeredFiles = await registerUploadedFiles(filesToUpload, filePaths, recommendations, uploadMetadataPayload);
            await finishUploadedFiles(registeredFiles, uploadMetadataPayload);
            if (sensitiveFileList.length) setSensitiveWordFiles(sensitiveFileList);
        } catch (error) {
            const message = error instanceof Error && error.message ? error.message : "上传失败";
            showToast({ message, severity: NotificationSeverity.ERROR });
        } finally {
            uploadSubmittingRef.current = false;
            setUploadSubmitting(false);
        }
    }, [activeSpace, businessDomainCode, finishUploadedFiles, recommendationParentId, recommendUploadTargetMap, registerUploadedFiles, resolveManualParentId, selectedFileSubcategory, selectedUploadTagValues, showToast, uploadFiles, uploadFolderSelection.mode, uploadLocalFolderName, uploadReviewRows.length]);

    const handleSensitiveWordDialogClose = useCallback(() => {
        setSensitiveWordFiles([]);
    }, []);

    const handleDuplicateSkip = useCallback(() => {
        setDuplicateFiles([]);
        setDuplicateFileCategoryCode(undefined);
        setDuplicateUploadMetadataPayload({});
    }, []);

    const handleDuplicateOverwrite = useCallback(async () => {
        if (!activeSpace || duplicateFiles.length === 0 || duplicateOverwriting) return;
        const fileObjs = duplicateFiles.map((file) => file.rawObj).filter(Boolean);
        if (fileObjs.length === 0) {
            showToast({ message: "文件覆盖失败：缺少重复文件信息", severity: NotificationSeverity.ERROR });
            return;
        }
        const retryMetadata = Object.keys(duplicateUploadMetadataPayload).length
            ? duplicateUploadMetadataPayload
            : (duplicateFileCategoryCode ? { file_category_code: duplicateFileCategoryCode } : undefined);
        setDuplicateOverwriting(true);
        try {
            await retryDuplicateFilesApi(activeSpace.id, fileObjs, retryMetadata);
            resetUploadDialog();
            await reloadFiles();
            showToast({ message: "覆盖成功，文件已进入解析队列", severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: "文件覆盖失败", severity: NotificationSeverity.ERROR });
        } finally {
            setDuplicateOverwriting(false);
        }
    }, [activeSpace, duplicateFileCategoryCode, duplicateFiles, duplicateOverwriting, duplicateUploadMetadataPayload, reloadFiles, resetUploadDialog, showToast]);

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
        uploadFolderSelection,
        uploadFolderNodes,
        uploadFolderLoading,
        uploadSubmitting,
        uploadImporting,
        uploadReviewRows,
        uploadFolderOptions,
        duplicateFiles,
        duplicateOverwriting,
        sensitiveWordFiles,
        fileSubcategoryCode,
        fileCategoryGroups,
        businessDomainCode,
        uploadTagOptions,
        selectedUploadTagValues,
        uploadTagLoading,
        fileInputAccept,
        supportedFormatsLabel,
        maxFileSizeMB,
        setUploadDialogOpen,
        setUploadStep,
        setUploadReviewRows,
        resetUploadDialog,
        handleOpenUploadDialog,
        handleAddUploadFiles,
        handleAddUploadFolder,
        handleRemoveUploadFile,
        handleSelectUploadFolder,
        handleUseAiUploadFolder,
        handleSelectFileCategory,
        handleSelectBusinessDomain,
        handleToggleUploadTag,
        handleClearUploadTags,
        handleToggleUploadFolder,
        handleUploadNext,
        handleStartUploadImport,
        handleDuplicateSkip,
        handleDuplicateOverwrite,
        handleSensitiveWordDialogClose,
    };
}
