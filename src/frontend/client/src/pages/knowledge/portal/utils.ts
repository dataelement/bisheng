import {
    FileStatus,
    FileType,
    fileStatusToNumber,
    type KnowledgeFile,
} from "~/api/knowledge";
import {
    DEFAULT_PORTAL_FILE_CATEGORY_GROUPS,
    DEFAULT_PORTAL_FILE_CATEGORY_OPTIONS,
    LEGACY_FILE_ICON_TYPE_BY_EXTENSION,
    type LegacyFileIconType,
} from "./constants";
import type {
    PortalFileCategoryGroupOption,
    PortalFileCategoryOption,
    PortalFileTreeNode,
    PortalUploadFolderNode,
} from "./types";
import { cleanEncodingText, normalizeEncodingCode } from "./uploadMetadata";
import { isKnowledgeFileReparseRetryable } from "../knowledgeUtils";

export function isFolder(file: KnowledgeFile) {
    return file.type === FileType.FOLDER;
}

export function normalizePortalFileCategoryOptions(rawOptions: unknown): PortalFileCategoryOption[] {
    if (!Array.isArray(rawOptions)) {
        return DEFAULT_PORTAL_FILE_CATEGORY_OPTIONS;
    }
    const seenCodes = new Set<string>();
    const options: PortalFileCategoryOption[] = [];
    rawOptions.forEach((item) => {
        if (!item || typeof item !== "object") return;
        const rawCode = (item as any).code;
        const rawLabel = (item as any).label ?? (item as any).name;
        const code = normalizeEncodingCode(typeof rawCode === "string" ? rawCode : "");
        const label = cleanEncodingText(typeof rawLabel === "string" ? rawLabel : "");
        if (!code || !label || seenCodes.has(code)) return;
        seenCodes.add(code);
        options.push({ code, label });
    });
    return options.length ? options : DEFAULT_PORTAL_FILE_CATEGORY_OPTIONS;
}

export function normalizePortalFileCategoryGroups(rawOptions: unknown): PortalFileCategoryGroupOption[] {
    if (!Array.isArray(rawOptions)) {
        return DEFAULT_PORTAL_FILE_CATEGORY_GROUPS;
    }
    const seenParentCodes = new Set<string>();
    const groups: PortalFileCategoryGroupOption[] = [];
    rawOptions.forEach((item) => {
        if (!item || typeof item !== "object") return;
        const rawCode = (item as any).code;
        const rawLabel = (item as any).label ?? (item as any).name;
        const parentCode = normalizeEncodingCode(typeof rawCode === "string" ? rawCode : "");
        const parentLabel = cleanEncodingText(typeof rawLabel === "string" ? rawLabel : "");
        if (!parentCode || !parentLabel || seenParentCodes.has(parentCode)) return;
        const rawChildren = Array.isArray((item as any).children) && (item as any).children.length
            ? (item as any).children
            : [{ code: rawCode, label: rawLabel }];
        const seenChildCodes = new Set<string>();
        const children: PortalFileCategoryGroupOption["children"] = [];
        rawChildren.forEach((child: unknown) => {
            if (!child || typeof child !== "object") return;
            const childCode = normalizeEncodingCode(typeof (child as any).code === "string" ? (child as any).code : "");
            const childLabel = cleanEncodingText(typeof (child as any).label === "string" ? (child as any).label : "");
            if (!childCode || !childLabel || seenChildCodes.has(childCode)) return;
            seenChildCodes.add(childCode);
            children.push({
                code: childCode,
                label: childLabel,
                parentCode,
                parentLabel,
                displayLabel: parentLabel === childLabel ? childLabel : `${parentLabel} / ${childLabel}`,
            });
        });
        if (!children.length) return;
        seenParentCodes.add(parentCode);
        groups.push({ code: parentCode, label: parentLabel, children });
    });
    return groups.length ? groups : DEFAULT_PORTAL_FILE_CATEGORY_GROUPS;
}

export function getPortalFileIconType(file: KnowledgeFile): LegacyFileIconType | "xlsx" {
    if (isFolder(file)) return "dir";
    const parts = file.name.split(".");
    const extension = parts.length > 1 ? parts.pop()?.toLowerCase() || "" : "";
    return LEGACY_FILE_ICON_TYPE_BY_EXTENSION[extension] || "txt";
}

export function isPreviewable(file: KnowledgeFile) {
    if (isFolder(file)) return false;
    return !file.status || file.status === FileStatus.SUCCESS || file.status === FileStatus.VIOLATION;
}

export function formatFileSize(size?: number) {
    if (!size || size <= 0) return "-";
    if (size < 1024) return `${size} B`;
    if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
    if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
    return `${(size / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function extractExtFromSource(source: string) {
    const cleanSource = source.split("?")[0].split("#")[0];
    const filePart = cleanSource.split("/").pop() || "";
    const dotIndex = filePart.lastIndexOf(".");
    if (dotIndex <= 0 || dotIndex >= filePart.length - 1) return "";
    const ext = filePart.slice(dotIndex + 1).toLowerCase();
    return /^[a-z0-9]{1,10}$/.test(ext) ? ext : "";
}

export function extractExt(fileName: string, fileUrl = "") {
    return extractExtFromSource(fileUrl) || extractExtFromSource(fileName) || "txt";
}

export function resolvePreviewUrl(url: string) {
    if (!url) return "";
    if (/^https?:\/\//.test(url)) return url;
    const baseUrl = typeof __APP_ENV__ !== "undefined" ? __APP_ENV__.BASE_URL : "";
    return `${window.location.origin}${baseUrl}${url}`;
}

export function resolveAssetUrl(path: string) {
    const baseUrl = typeof __APP_ENV__ !== "undefined" ? __APP_ENV__.BASE_URL || "" : "";
    return `${baseUrl.replace(/\/$/, "")}${path}`;
}

export function statusText(file: KnowledgeFile) {
    switch (file.status) {
        case FileStatus.UPLOADING:
            return "上传中";
        case FileStatus.PROCESSING:
            return "解析中";
        case FileStatus.WAITING:
            return "排队中";
        case FileStatus.REBUILDING:
            return "重建中";
        case FileStatus.SUCCESS:
            return "成功";
        case FileStatus.FAILED:
            return "失败";
        case FileStatus.TIMEOUT:
            return "超时";
        case FileStatus.VIOLATION:
            return "违规";
        default:
            return "";
    }
}

export function createTreeNode(file: KnowledgeFile): PortalFileTreeNode {
    return {
        file,
        children: [],
        expanded: false,
        loaded: false,
        loading: false,
        page: 1,
        total: 0,
        hasMore: false,
        nextCursor: null,
    };
}

/**
 * Merge a fresh root listing with the previous tree so already-loaded folder
 * children survive a late root refresh (deep-link navigate vs loadRootTree race).
 */
export function mergeRootTreeNodesPreservingLoadedFolders(
    previous: PortalFileTreeNode[],
    rootFiles: KnowledgeFile[],
    currentFolderId?: string,
): PortalFileTreeNode[] {
    const nextNodes = dedupeFilesById(rootFiles).map((file) => {
        const next = createTreeNode(file);
        if (!isFolder(file)) return next;
        const prevNode = findTreeNode(previous, String(file.id));
        // Keep expanded folder contents; refresh folder row metadata from root.
        if (!prevNode?.loaded) return next;
        return {
            ...next,
            children: prevNode.children,
            expanded: prevNode.expanded,
            loaded: prevNode.loaded,
            loading: prevNode.loading,
            page: prevNode.page,
            total: prevNode.total,
            hasMore: prevNode.hasMore,
            nextCursor: prevNode.nextCursor,
        };
    });
    if (!currentFolderId) return nextNodes;
    if (findTreeNode(nextNodes, currentFolderId)) return nextNodes;
    const currentFolderNode = findTreeNode(previous, currentFolderId);
    if (!currentFolderNode) return nextNodes;
    return dedupeTreeNodesByFileId([currentFolderNode, ...nextNodes]);
}

export function dedupeFilesById(files: KnowledgeFile[]): KnowledgeFile[] {
    const seen = new Set<string>();
    return files.filter((file) => {
        const id = String(file.id || "");
        if (!id) return true;
        if (seen.has(id)) return false;
        seen.add(id);
        return true;
    });
}

export function dedupeTreeNodesByFileId(nodes: PortalFileTreeNode[]): PortalFileTreeNode[] {
    const seen = new Set<string>();
    return nodes
        .filter((node) => {
            const id = String(node.file.id || "");
            if (!id) return true;
            if (seen.has(id)) return false;
            seen.add(id);
            return true;
        })
        .map((node) => ({
            ...node,
            children: dedupeTreeNodesByFileId(node.children),
        }));
}

export function flattenTreeFiles(nodes: PortalFileTreeNode[]): KnowledgeFile[] {
    return nodes.flatMap((node) => [
        node.file,
        ...(node.expanded ? flattenTreeFiles(node.children) : []),
    ]);
}

export function collectTreeFileIds(nodes: PortalFileTreeNode[]): string[] {
    return nodes.flatMap((node) => [node.file.id, ...collectTreeFileIds(node.children)]);
}

export function findTreeNode(nodes: PortalFileTreeNode[], fileId: string): PortalFileTreeNode | null {
    for (const node of nodes) {
        if (node.file.id === fileId) return node;
        const child = findTreeNode(node.children, fileId);
        if (child) return child;
    }
    return null;
}

export function findTreeNodePath(
    nodes: PortalFileTreeNode[],
    fileId: string,
    path: Array<{ id?: string; name: string }> = [],
): Array<{ id?: string; name: string }> {
    for (const node of nodes) {
        const nextPath = [...path, { id: node.file.id, name: node.file.name }];
        if (node.file.id === fileId) return nextPath;
        const childPath = findTreeNodePath(node.children, fileId, nextPath);
        if (childPath.length) return childPath;
    }
    return [];
}

export function updateTreeNode(
    nodes: PortalFileTreeNode[],
    fileId: string,
    updater: (node: PortalFileTreeNode) => PortalFileTreeNode,
): PortalFileTreeNode[] {
    return nodes.map((node) => {
        if (node.file.id === fileId) {
            return updater(node);
        }
        if (!node.children.length) return node;
        return {
            ...node,
            children: updateTreeNode(node.children, fileId, updater),
        };
    });
}

export function createRestoredFolderFile(
    spaceId: string,
    folderId: string,
    folderName?: string,
): KnowledgeFile {
    const name = folderName?.trim() || `文件夹 ${folderId}`;
    return {
        id: folderId,
        name,
        type: FileType.FOLDER,
        tags: [],
        path: name,
        spaceId,
        createdAt: "",
        updatedAt: "",
    };
}

/**
 * Ensure a chain of ancestor folders exists in the tree, creating placeholder
 * nodes for any missing segments. Used when restoring a deep-linked/returned
 * folder so the breadcrumb can show the full path instead of only the deepest
 * folder.
 */
export function ensureFolderPath(
    nodes: PortalFileTreeNode[],
    path: Array<{ id: string; name: string }>,
    spaceId: string,
): PortalFileTreeNode[] {
    if (!path.length) return nodes;
    const [head, ...tail] = path;
    const headId = String(head.id);
    const index = nodes.findIndex((node) => String(node.file.id) === headId);
    if (index >= 0) {
        const node = nodes[index];
        const nextNode: PortalFileTreeNode = {
            ...node,
            expanded: true,
            children: ensureFolderPath(node.children, tail, spaceId),
        };
        return [...nodes.slice(0, index), nextNode, ...nodes.slice(index + 1)];
    }
    const newNode: PortalFileTreeNode = {
        ...createTreeNode(createRestoredFolderFile(spaceId, headId, head.name)),
        expanded: true,
        children: ensureFolderPath([], tail, spaceId),
    };
    return [...nodes, newNode];
}

export function createUploadFolderNode(item: { id: number | string; file_name?: string; name?: string }): PortalUploadFolderNode {
    return {
        id: String(item.id),
        name: String(item.file_name ?? item.name ?? ""),
        children: [],
        expanded: false,
        loaded: false,
        loading: false,
    };
}

export function updateUploadFolderNode(
    nodes: PortalUploadFolderNode[],
    folderId: string,
    updater: (node: PortalUploadFolderNode) => PortalUploadFolderNode,
): PortalUploadFolderNode[] {
    return nodes.map((node) => {
        if (node.id === folderId) return updater(node);
        if (!node.children.length) return node;
        return {
            ...node,
            children: updateUploadFolderNode(node.children, folderId, updater),
        };
    });
}

export function flattenUploadFolders(nodes: PortalUploadFolderNode[]): Array<{ id: string; name: string }> {
    return nodes.flatMap((node) => [
        { id: node.id, name: node.name },
        ...flattenUploadFolders(node.children),
    ]);
}

export function folderCountText(file: KnowledgeFile) {
    if (file.folderStatsLoading) return "加载中";
    if (file.folderStatsError) return "--";
    if (file.successFileNum === undefined || file.fileNum === undefined) return "";
    return `(${file.successFileNum}/${file.fileNum})`;
}

export function isRetryable(file: KnowledgeFile) {
    return isKnowledgeFileReparseRetryable(file);
}

export function toNumericIds(files: KnowledgeFile[]) {
    return files
        .map((file) => Number(file.id))
        .filter((id) => Number.isFinite(id));
}

export function toStatusNumbers(statuses: FileStatus[]) {
    return statuses
        .map(fileStatusToNumber)
        .filter((status) => Number.isFinite(status));
}
