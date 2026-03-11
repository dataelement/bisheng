import request from "./request";

// 文件状态
export enum FileStatus {
    UPLOADING = "uploading",
    QUEUED = "queued",
    PROCESSING = "processing",
    SUCCESS = "success",
    FAILED = "failed",
    TIMEOUT = "timeout"
}

// 文件类型
export enum FileType {
    FOLDER = "folder",
    PDF = "pdf",
    DOC = "doc",
    DOCX = "docx",
    XLS = "xls",
    XLSX = "xlsx",
    PPT = "ppt",
    PPTX = "pptx",
    JPG = "jpg",
    JPEG = "jpeg",
    PNG = "png",
    OTHER = "other"
}

// 可见方式
export enum VisibilityType {
    PUBLIC = "public",      // 公开
    PRIVATE = "private"     // 私有
}

// 排序类型
export enum SortType {
    NAME = "name",
    TYPE = "type",
    SIZE = "size",
    UPDATE_TIME = "update_time"
}

// 排序方向
export enum SortDirection {
    ASC = "asc",
    DESC = "desc"
}

// 知识空间角色
export enum SpaceRole {
    CREATOR = "creator",
    ADMIN = "admin",
    MEMBER = "member"
}

// 知识空间接口
export interface KnowledgeSpace {
    id: string;
    name: string;
    description?: string;
    visibility: VisibilityType;
    creator: string;
    creatorId: string;
    memberCount: number;
    fileCount: number;       // 成功入库的文件数
    totalFileCount: number;  // 总文件数
    role: SpaceRole;
    isPinned: boolean;
    createdAt: string;
    updatedAt: string;
    tags: string[];          // 空间标签池
}

// 文件/文件夹接口
export interface KnowledgeFile {
    id: string;
    name: string;
    type: FileType;
    size?: number;           // 文件大小（字节），文件夹无此字段
    status?: FileStatus;     // 处理状态（文件夹无此字段）
    tags: string[];
    path: string;            // 完整路径
    parentId?: string;       // 父文件夹ID
    spaceId: string;
    createdAt: string;
    updatedAt: string;
    thumbnail?: string;      // 缩略图URL
    errorMessage?: string;   // 失败原因
}

/**
 * 获取知识空间列表
 */
export async function getKnowledgeSpacesApi(params: {
    type: "created" | "joined";
}): Promise<KnowledgeSpace[]> {
    return await request.get(`/api/v1/knowledge-spaces`, { params });
}

/**
 * 创建知识空间
 */
export async function createKnowledgeSpaceApi(data: {
    name: string;
    description?: string;
    visibility: VisibilityType;
}): Promise<KnowledgeSpace> {
    return await request.post(`/api/v1/knowledge-spaces`, data);
}

/**
 * 更新知识空间
 */
export async function updateKnowledgeSpaceApi(spaceId: string, data: {
    name?: string;
    description?: string;
    visibility?: VisibilityType;
}): Promise<KnowledgeSpace> {
    return await request.put(`/api/v1/knowledge-spaces/${spaceId}`, data);
}

/**
 * 删除知识空间
 */
export async function deleteKnowledgeSpaceApi(spaceId: string): Promise<void> {
    return await request.delete(`/api/v1/knowledge-spaces/${spaceId}`);
}

/**
 * 退出知识空间
 */
export async function leaveKnowledgeSpaceApi(spaceId: string): Promise<void> {
    return await request.post(`/api/v1/knowledge-spaces/${spaceId}/leave`);
}

/**
 * 置顶知识空间
 */
export async function pinKnowledgeSpaceApi(spaceId: string, pinned: boolean): Promise<void> {
    return await request.post(`/api/v1/knowledge-spaces/${spaceId}/pin`, { pinned });
}

/**
 * 获取文件列表
 */
export async function getFilesApi(params: {
    spaceId: string;
    parentId?: string;       // 父文件夹ID，不传则为根目录
    search?: string;
    searchScope?: "current" | "space";  // 搜索范围
    statusFilter?: FileStatus[];
    sortBy?: SortType;
    sortDirection?: SortDirection;
    page?: number;
    pageSize?: number;
}): Promise<{
    data: KnowledgeFile[];
    total: number;
}> {
    return await request.get(`/api/v1/knowledge-spaces/${params.spaceId}/files`, { params });
}

/**
 * 上传文件
 */
export async function uploadFileApi(spaceId: string, parentId: string | undefined, file: File): Promise<KnowledgeFile> {
    const formData = new FormData();
    formData.append('file', file);
    if (parentId) {
        formData.append('parentId', parentId);
    }
    return await request.postMultiPart(`/api/v1/knowledge-spaces/${spaceId}/files`, formData);
}

/**
 * 创建文件夹
 */
export async function createFolderApi(data: {
    spaceId: string;
    parentId?: string;
    name: string;
}): Promise<KnowledgeFile> {
    return await request.post(`/api/v1/knowledge-spaces/${data.spaceId}/folders`, data);
}

/**
 * 重命名文件/文件夹
 */
export async function renameFileApi(fileId: string, name: string): Promise<void> {
    return await request.put(`/api/v1/files/${fileId}/rename`, { name });
}

/**
 * 删除文件/文件夹
 */
export async function deleteFileApi(fileId: string): Promise<void> {
    return await request.delete(`/api/v1/files/${fileId}`);
}

/**
 * 批量删除
 */
export async function batchDeleteFilesApi(fileIds: string[]): Promise<void> {
    return await request.post(`/api/v1/files/batch-delete`, { fileIds });
}

/**
 * 编辑标签
 */
export async function updateFileTagsApi(fileId: string, tags: string[]): Promise<void> {
    return await request.put(`/api/v1/files/${fileId}/tags`, { tags });
}

/**
 * 批量添加标签
 */
export async function batchAddTagsApi(fileIds: string[], tags: string[]): Promise<void> {
    return await request.post(`/api/v1/files/batch-add-tags`, { fileIds, tags });
}

/**
 * 重试失败文件
 */
export async function retryFileApi(fileId: string): Promise<void> {
    return await request.post(`/api/v1/files/${fileId}/retry`);
}

/**
 * 批量重试
 */
export async function batchRetryFilesApi(fileIds: string[]): Promise<void> {
    return await request.post(`/api/v1/files/batch-retry`, { fileIds });
}

/**
 * 下载文件
 */
export async function downloadFileApi(fileId: string): Promise<Blob> {
    return await request.get(`/api/v1/files/${fileId}/download`, { responseType: 'blob' });
}

/**
 * 批量下载
 */
export async function batchDownloadFilesApi(fileIds: string[]): Promise<Blob> {
    return await request.post(`/api/v1/files/batch-download`, { fileIds }, { responseType: 'blob' });
}
