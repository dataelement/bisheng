import {
    FileStatus,
    FileType,
    fileStatusToNumber,
    type KnowledgeFile,
} from "~/api/knowledge";
import { LEGACY_FILE_ICON_TYPE_BY_EXTENSION, type LegacyFileIconType } from "./constants";
import type { PortalFileTreeNode, PortalUploadFolderNode } from "./types";

export function isFolder(file: KnowledgeFile) {
    return file.type === FileType.FOLDER;
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

export function extractExt(fileName: string, fileUrl = "") {
    const source = fileName || fileUrl.split("?")[0] || "";
    const ext = source.split(".").pop()?.toLowerCase() || "";
    return ext || "txt";
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
    };
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
    if (file.successFileNum === undefined || file.fileNum === undefined) return "";
    return `(${file.successFileNum}/${file.fileNum})`;
}

export function isRetryable(file: KnowledgeFile) {
    if (file.status === FileStatus.FAILED || file.status === FileStatus.VIOLATION) return true;
    if (isFolder(file) && file.successFileNum !== undefined && file.fileNum !== undefined) {
        return file.successFileNum < file.fileNum;
    }
    return false;
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
