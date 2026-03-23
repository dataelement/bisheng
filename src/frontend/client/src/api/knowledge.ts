import request from "./request";

// Standard backend response wrapper
interface ApiResponse<T> {
    status_code: number;
    status_message: string;
    data: T;
}

// ─────────────────────────────────────────────
// Enums (kept aligned with backend value strings)
// ─────────────────────────────────────────────

/** File processing status */
export enum FileStatus {
    UPLOADING = "uploading",
    PROCESSING = "processing",
    SUCCESS = "success",
    FAILED = "failed",
    REBUILDING = "rebuilding",
    WAITING = "waiting",
    TIMEOUT = "timeout"
}

/** File / folder type used for UI rendering */
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

/** Space visibility / auth type */
export enum VisibilityType {
    PUBLIC = "public",
    PRIVATE = "private"
}

/** Sort field */
export enum SortType {
    NAME = "file_name",
    TYPE = "file_type",
    SIZE = "file_size",
    UPDATE_TIME = "update_time"
}

/** Sort direction */
export enum SortDirection {
    ASC = "asc",
    DESC = "desc"
}

/** User role within a space */
export enum SpaceRole {
    CREATOR = "creator",
    ADMIN = "admin",
    MEMBER = "member"
}

// ─────────────────────────────────────────────
// Frontend domain interfaces (used by components)
// ─────────────────────────────────────────────

/** Knowledge space model used throughout the UI */
export interface KnowledgeSpace {
    id: string;
    name: string;
    description?: string;
    icon?: string;
    visibility: VisibilityType;   // mapped from auth_type
    creator: string;              // mapped from user_name
    creatorId: string;            // mapped from user_id
    memberCount: number;          // mapped from member_count
    fileCount: number;            // success-indexed file count
    totalFileCount: number;
    role: SpaceRole;
    isPinned: boolean;
    createdAt: string;            // mapped from create_time
    updatedAt: string;            // mapped from update_time
    tags: string[];
    isReleased: boolean;          // mapped from is_released
}

/** File or folder item returned from the space children API */
export interface FileTag {
    id: number;
    name: string;
}

export interface KnowledgeFile {
    id: string;
    name: string;
    type: FileType;
    size?: number;
    status?: FileStatus;
    tags: FileTag[];
    path: string;
    parentId?: string;           // mapped from parent_id
    spaceId: string;
    createdAt: string;           // mapped from create_time
    updatedAt: string;           // mapped from update_time
    thumbnail?: string;
    errorMessage?: string;
    /** Number of successfully parsed files (folders only) */
    successFileNum?: number;
    /** Total number of files (folders only) */
    fileNum?: number;
    // Transient UI-only fields
    isCreating?: boolean;
}

// ─────────────────────────────────────────────
// Backend raw types (snake_case from API responses)
// ─────────────────────────────────────────────

interface RawKnowledgeSpace {
    id: number;
    name: string;
    description?: string;
    icon?: string;
    auth_type: string;           // "public" | "private"
    user_name?: string;
    user_id?: number;
    member_count?: number;
    file_count?: number;
    total_file_count?: number;
    role?: string;
    user_role?: string;
    is_pinned?: boolean;
    create_time?: string;
    update_time?: string;
    tags?: string[];
    is_released?: boolean;
}

interface RawSpaceChild {
    id: number;
    name: string;
    /** "folder" | "file" */
    type: string;
    /** For files: "pdf" | "docx" | etc. */
    file_type?: string;
    size?: number;
    status?: string;
    tags?: string[];
    path?: string;
    parent_id?: number;
    space_id?: number;
    create_time?: string;
    update_time?: string;
    thumbnail?: string;
    error_message?: string;
}

/** Raw file record returned by addFiles / knowledge file APIs */
interface RawKnowledgeFile {
    id: number;
    knowledge_id: number;
    file_name: string;
    /** Numeric file type from backend (e.g. 1 = docx, etc.) */
    file_type: number;
    /** Numeric status: 1 = processing, 2 = failed, 3 = success */
    status: number;
    file_size?: number;
    object_name?: string;
    file_path?: string;
    file_level_path?: string;
    level?: number;
    user_name?: string;
    user_id?: number;
    create_time?: string;
    update_time?: string;
    remark?: string;
    thumbnails?: string | null;
    success_file_num?: number;
    file_num?: number;
    tags?: Array<{ id: number; name: string }>;
}

/** Upload API response */
export interface UploadFileResponse {
    file_name: string;
    file_path: string;
    flowId: string | null;
    relative_path: string | null;
    repeat: boolean;
    repeat_file_name: string | null;
    repeat_update_time: string | null;
}

// ─────────────────────────────────────────────
// Mapper functions (backend → frontend)
// ─────────────────────────────────────────────

/** Map a raw backend space to the frontend KnowledgeSpace model */
function mapSpace(raw: RawKnowledgeSpace): KnowledgeSpace {
    return {
        id: String(raw.id),
        name: raw.name,
        description: raw.description,
        icon: raw.icon,
        visibility: (raw.auth_type as VisibilityType) || VisibilityType.PRIVATE,
        creator: raw.user_name || "",
        creatorId: String(raw.user_id ?? ""),
        memberCount: raw.member_count ?? 0,
        fileCount: raw.file_count ?? 0,
        totalFileCount: raw.total_file_count ?? 0,
        role: (raw.user_role as SpaceRole) || (raw.role as SpaceRole) || SpaceRole.MEMBER,
        isPinned: raw.is_pinned ?? false,
        createdAt: raw.create_time || "",
        updatedAt: raw.update_time || "",
        tags: raw.tags || [],
        isReleased: raw.is_released ?? false,
    };
}

/** Derive explicit FileType enum value from a raw child item */
function deriveFileType(raw: RawSpaceChild): FileType {
    if (raw.type === "folder") return FileType.FOLDER;
    const ext = (raw.file_type || "").toLowerCase();
    switch (ext) {
        case "pdf": return FileType.PDF;
        case "doc": return FileType.DOC;
        case "docx": return FileType.DOCX;
        case "xls": return FileType.XLS;
        case "xlsx": return FileType.XLSX;
        case "ppt": return FileType.PPT;
        case "pptx": return FileType.PPTX;
        case "jpg": return FileType.JPG;
        case "jpeg": return FileType.JPEG;
        case "png": return FileType.PNG;
        default: return FileType.OTHER;
    }
}

/** Map a raw space child (file/folder) to the frontend KnowledgeFile model */
function mapChild(raw: RawSpaceChild, spaceId: string): KnowledgeFile {
    return {
        id: String(raw.id),
        name: raw.name,
        type: deriveFileType(raw),
        size: raw.size,
        status: raw.status as FileStatus | undefined,
        tags: raw.tags || [],
        path: raw.path || raw.name,
        parentId: raw.parent_id !== undefined ? String(raw.parent_id) : undefined,
        spaceId: raw.space_id !== undefined ? String(raw.space_id) : spaceId,
        createdAt: raw.create_time || "",
        updatedAt: raw.update_time || "",
        thumbnail: raw.thumbnail,
        errorMessage: raw.error_message,
    };
}

/** Derive FileType from file extension in file_name */
function deriveFileTypeFromName(fileName: string): FileType {
    const ext = fileName.split('.').pop()?.toLowerCase() || "";
    switch (ext) {
        case "pdf": return FileType.PDF;
        case "doc": return FileType.DOC;
        case "docx": return FileType.DOCX;
        case "xls": return FileType.XLS;
        case "xlsx": return FileType.XLSX;
        case "ppt": return FileType.PPT;
        case "pptx": return FileType.PPTX;
        case "jpg": return FileType.JPG;
        case "jpeg": return FileType.JPEG;
        case "png": return FileType.PNG;
        default: return FileType.OTHER;
    }
}

/** Map numeric status to FileStatus enum */
function mapFileStatus(status: number): FileStatus {
    switch (status) {
        case 1: return FileStatus.PROCESSING;
        case 2: return FileStatus.SUCCESS;
        case 3: return FileStatus.FAILED;
        case 4: return FileStatus.REBUILDING;
        case 5: return FileStatus.WAITING;
        case 6: return FileStatus.TIMEOUT;
        default: return FileStatus.WAITING;
    }
}

/** Convert FileStatus enum to backend numeric value */
export function fileStatusToNumber(status: FileStatus): number {
    switch (status) {
        case FileStatus.PROCESSING: return 1;
        case FileStatus.SUCCESS: return 2;
        case FileStatus.FAILED: return 3;
        case FileStatus.REBUILDING: return 4;
        case FileStatus.WAITING: return 5;
        case FileStatus.TIMEOUT: return 6;
        default: return 0;
    }
}

/** Map a raw knowledge file record to the frontend KnowledgeFile model */
function mapRawFile(raw: RawKnowledgeFile): KnowledgeFile {
    const isFolder = raw.file_type === 0;
    return {
        id: String(raw.id),
        name: raw.file_name,
        type: isFolder ? FileType.FOLDER : deriveFileTypeFromName(raw.file_name),
        size: raw.file_size,
        status: isFolder ? undefined : mapFileStatus(raw.status),
        tags: isFolder ? [] : (raw.tags || []),
        path: raw.object_name || raw.file_name,
        parentId: undefined,
        spaceId: String(raw.knowledge_id),
        createdAt: raw.create_time || "",
        updatedAt: raw.update_time || "",
        thumbnail: raw.thumbnails || undefined,
        successFileNum: raw.success_file_num,
        fileNum: raw.file_num,
    };
}

// ─────────────────────────────────────────────
// API functions — Space management
// ─────────────────────────────────────────────

/**
 * Get spaces created by the current user
 */
export async function getMineSpacesApi(params?: {
    order_by?: string;
}): Promise<KnowledgeSpace[]> {
    const res = await request.get<ApiResponse<RawKnowledgeSpace[]>>(`/api/v1/knowledge/space/mine`, { params });
    return (res?.data || []).map(mapSpace);
}

/**
 * Get spaces joined by the current user
 */
export async function getJoinedSpacesApi(params?: {
    order_by?: string;
}): Promise<KnowledgeSpace[]> {
    const res = await request.get<ApiResponse<RawKnowledgeSpace[]>>(`/api/v1/knowledge/space/joined`, { params });
    return (res?.data || []).map(mapSpace);
}

/**
 * Get public knowledge square (paginated)
 * Response items are { space, is_followed, is_pending } — flatten to ChannelSquare-compatible format
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function getSquareSpacesApi(params?: {
    keyword?: string;
    page?: number;
    page_size?: number;
}): Promise<{ data: { data: any[]; total: number } }> {
    interface SquareItem {
        space: RawKnowledgeSpace;
        is_followed: boolean;
        is_pending: boolean;
    }
    const res = await request.get<ApiResponse<{ total: number; data: SquareItem[] }>>(
        `/api/v1/knowledge/space/square`,
        { params }
    );
    const items = (res?.data?.data || []).map((item) => ({
        id: item.space?.id,
        name: item.space?.name ?? "",
        description: item.space?.description ?? "",
        creator: "",
        auth_type: item.space?.auth_type,
        visibility: item.space?.auth_type,
        subscription_status: item.is_followed
            ? "subscribed"
            : item.is_pending
                ? "pending"
                : "not_subscribed",
    }));
    return {
        data: {
            data: items,
            total: res?.data?.total ?? 0,
        },
    };
}

/**
 * Create a new knowledge space
 */
export async function createSpaceApi(data: {
    name: string;
    description?: string;
    icon?: string;
    auth_type: string;
    is_released?: boolean;
}): Promise<KnowledgeSpace> {
    const res = await request.post(`/api/v1/knowledge/space`, data) as ApiResponse<RawKnowledgeSpace>;
    return mapSpace(res.data);
}

/**
 * Update an existing knowledge space
 */
export async function updateSpaceApi(
    space_id: string,
    data: {
        name?: string;
        description?: string;
        icon?: string;
        auth_type?: string;
        is_released?: boolean;
    }
): Promise<KnowledgeSpace> {
    if (!space_id) throw new Error("space_id is required");
    const res = await request.put(`/api/v1/knowledge/space/${space_id}`, data) as ApiResponse<RawKnowledgeSpace>;
    return mapSpace(res.data);
}

/**
 * Get space detail info
 */
export async function getSpaceInfoApi(space_id: string): Promise<KnowledgeSpace> {
    if (!space_id) throw new Error("space_id is required");
    const res = await request.get<ApiResponse<RawKnowledgeSpace>>(
        `/api/v1/knowledge/space/${space_id}/info`
    );
    return mapSpace(res.data);
}

/**
 * Get members of a space
 */
export async function getSpaceMembersApi(space_id: string): Promise<unknown[]> {
    return request.get(`/api/v1/knowledge/space/${space_id}/members`);
}

/**
 * Subscribe to a space
 * POST /api/v1/knowledge/space/{space_id}/subscribe
 */
export async function subscribeSpaceApi(space_id: string): Promise<void> {
    await request.post(`/api/v1/knowledge/space/${space_id}/subscribe`);
}

/**
 * Unsubscribe from a space (leave)
 * POST /api/v1/knowledge/space/{space_id}/unsubscribe
 */
export async function unsubscribeSpaceApi(space_id: string): Promise<void> {
    await request.post(`/api/v1/knowledge/space/${space_id}/unsubscribe`);
}

/**
 * Delete a space
 * DELETE /api/v1/knowledge/space/{space_id}
 */
export async function deleteSpaceApi(space_id: string): Promise<void> {
    await request.delete(`/api/v1/knowledge/space/${space_id}`);
}

/**
 * Get the parent folder chain for a folder/file
 * GET /api/v1/knowledge/space/{space_id}/folders/{folder_id}/parent
 * Returns the ancestor path from root to the given folder
 */
export async function getFolderParentPathApi(
    spaceId: string,
    folderId: string
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
): Promise<Array<{ id: string; name: string }>> {
    const res = await request.get<ApiResponse<any>>(
        `/api/v1/knowledge/space/${spaceId}/folders/${folderId}/parent`
    );
    const data = res?.data;
    // Normalize: backend may return an array of objects with id/name or file_name
    if (Array.isArray(data)) {
        return data.map((item: any) => ({
            id: String(item.id),
            name: item.name || item.file_name || String(item.id),
        }));
    }
    return [];
}

/**
 * Pin / unpin a space
 * POST /api/v1/knowledge/space/{space_id}/set-pin
 * @param is_pined - true to pin, false to unpin (backend field name: is_pined)
 */
export async function pinSpaceApi(space_id: string, is_pined: boolean): Promise<void> {
    await request.post(`/api/v1/knowledge/space/${space_id}/set-pin`, { is_pined });
}

/**
 * Get items (folders and files) under a space directory
 * If parent_id is omitted, returns root-level items
 */
export async function getSpaceChildrenApi(params: {
    space_id: string;
    parent_id?: string;
    page?: number;
    page_size?: number;
    order_field?: string;
    order_sort?: string;
    file_status?: number[];
}): Promise<{ data: KnowledgeFile[]; total: number }> {
    const { space_id, ...queryParams } = params;
    if (!space_id) return { data: [], total: 0 };
    const res = await request.get<ApiResponse<{ data: RawKnowledgeFile[]; total: number }>>(
        `/api/v1/knowledge/space/${space_id}/children`,
        {
            params: {
                parent_id: queryParams.parent_id,
                page: queryParams.page,
                page_size: queryParams.page_size,
                order_field: queryParams.order_field,
                order_sort: queryParams.order_sort,
                file_status: queryParams.file_status?.length ? queryParams.file_status : undefined,
            },
            paramsSerializer,
        }
    );
    return {
        data: (res?.data?.data || []).map(mapRawFile),
        total: res?.data?.total ?? 0,
    };
}

/**
 * Search files under a space with keyword and/or tag filters
 * GET /api/v1/knowledge/space/{space_id}/search
 */
/** Serialize params so arrays become key=val1&key=val2 (not key[]=...) */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const paramsSerializer = (params: any) => {
    return Object.keys(params)
        .map(key => {
            const value = params[key];
            if (value === undefined) return null;
            if (Array.isArray(value)) {
                return value.map(val => `${key}=${val}`).join('&');
            }
            return `${key}=${value}`;
        })
        .filter(item => item !== null)
        .join('&');
};

export async function searchSpaceChildrenApi(params: {
    space_id: string;
    parent_id?: string;
    page?: number;
    page_size?: number;
    keyword?: string;
    tag_ids?: number[];
    order_field?: string;
    order_sort?: string;
    file_status?: number[];
}): Promise<{ data: KnowledgeFile[]; total: number }> {
    const { space_id, ...queryParams } = params;
    if (!space_id) return { data: [], total: 0 };
    const res = await request.get<ApiResponse<{ data: RawKnowledgeFile[]; total: number }>>(
        `/api/v1/knowledge/space/${space_id}/search`,
        {
            params: {
                parent_id: queryParams.parent_id,
                page: queryParams.page,
                page_size: queryParams.page_size,
                keyword: queryParams.keyword || undefined,
                tag_ids: queryParams.tag_ids?.length ? queryParams.tag_ids : undefined,
                order_field: queryParams.order_field,
                order_sort: queryParams.order_sort,
                file_status: queryParams.file_status?.length ? queryParams.file_status : undefined,
            },
            paramsSerializer,
        }
    );
    return {
        data: (res?.data?.data || []).map(mapRawFile),
        total: res?.data?.total ?? 0,
    };
}

// ─────────────────────────────────────────────
// API functions — Folder management
// ─────────────────────────────────────────────

/**
 * Create a new folder inside a space
 */
export async function createFolderApi(
    space_id: string,
    data: { name: string; parent_id?: string | null }
): Promise<KnowledgeFile> {
    const res = await request.post(
        `/api/v1/knowledge/space/${space_id}/folders`,
        {
            name: data.name,
            parent_id: data.parent_id ? Number(data.parent_id) : null,
        }
    ) as ApiResponse<RawSpaceChild>;
    return mapChild(res.data, space_id);
}

/**
 * Rename a folder
 */
export async function renameFolderApi(
    space_id: string,
    folder_id: string,
    name: string
): Promise<void> {
    return request.put(`/api/v1/knowledge/space/${space_id}/folders/${folder_id}`, { name });
}

/**
 * Delete a folder (recursively deletes all children)
 */
export async function deleteFolderApi(space_id: string, folder_id: string): Promise<void> {
    return request.delete(`/api/v1/knowledge/space/${space_id}/folders/${folder_id}`);
}

// ─────────────────────────────────────────────
// API functions — File management
// ─────────────────────────────────────────────

/**
 * Step 1: Upload a file to the server and get back its server path
 * Returns the upload response containing file_path to use in addFilesApi
 */
export async function uploadFileToServerApi(
    space_id: string,
    file: File
): Promise<UploadFileResponse> {
    const formData = new FormData();
    formData.append("file", file);
    const res = await request.postMultiPart(`/api/v1/knowledge/upload/${space_id}`, formData) as ApiResponse<UploadFileResponse>;
    return res.data;
}

/**
 * Step 2: Register uploaded file paths into a knowledge space
 */
export async function addFilesApi(
    space_id: string,
    data: { file_path: string[]; parent_id?: number | null }
): Promise<KnowledgeFile[]> {
    const res = await request.post(
        `/api/v1/knowledge/space/${space_id}/files`,
        data
    ) as ApiResponse<RawKnowledgeFile[]>;
    return (res?.data || []).map(mapRawFile);
}

/**
 * Rename a file
 */
export async function renameFileApi(
    space_id: string,
    file_id: string,
    name: string
): Promise<void> {
    return request.put(`/api/v1/knowledge/space/${space_id}/files/${file_id}`, { name });
}

/**
 * Delete a single file
 */
export async function deleteFileApi(space_id: string, file_id: string): Promise<void> {
    return request.delete(`/api/v1/knowledge/space/${space_id}/files/${file_id}`);
}

// ─────────────────────────────────────────────
// API functions — Batch operations
// ─────────────────────────────────────────────

/**
 * Batch delete files and/or folders
 */
export async function batchDeleteApi(
    space_id: string,
    data: { file_ids?: number[]; folder_ids?: number[] }
): Promise<void> {
    return request.post(`/api/v1/knowledge/space/${space_id}/files/batch-delete`, data);
}

/**
 * Batch download files and/or folders (returns a download URL or triggers download)
 */
export async function batchDownloadApi(
    space_id: string,
    data: { file_ids?: number[]; folder_ids?: number[] }
): Promise<Blob> {
    return request.post(
        `/api/v1/knowledge/space/${space_id}/files/batch-download`,
        data,
        { responseType: "blob" }
    );
}

// ─────────────────────────────────────────────
// API functions — Tag management
// ─────────────────────────────────────────────

/** Tag entity returned by the backend */
export interface SpaceTag {
    id: number;
    name: string;
    business_type: string;
    business_id: string;
    user_id: number;
    create_time: string;
    update_time: string;
}

/**
 * Get all tags for a knowledge space
 * GET /api/v1/knowledge/space/{space_id}/tag
 */
export async function getSpaceTagsApi(space_id: string): Promise<SpaceTag[]> {
    const res = await request.get<ApiResponse<SpaceTag[]>>(
        `/api/v1/knowledge/space/${space_id}/tag`
    );
    return res?.data || [];
}

/**
 * Add a new tag to a knowledge space
 * POST /api/v1/knowledge/space/{space_id}/tag
 */
export async function addSpaceTagApi(
    space_id: string,
    tag_name: string
): Promise<SpaceTag> {
    const res = await request.post(
        `/api/v1/knowledge/space/${space_id}/tag`,
        { tag_name }
    ) as ApiResponse<SpaceTag>;
    return res.data;
}

/**
 * Delete a tag from a knowledge space
 * DELETE /api/v1/knowledge/space/{space_id}/tag
 */
export async function deleteSpaceTagApi(
    space_id: string,
    tag_id: number
): Promise<void> {
    await request.delete(`/api/v1/knowledge/space/${space_id}/tag`, {
        data: { tag_id },
    });
}

/**
 * Update (overwrite) tags for a single file
 * POST /api/v1/knowledge/space/{space_id}/files/{file_id}/tag
 */
export async function updateFileTagsApi(
    space_id: string,
    file_id: string,
    tag_ids: number[]
): Promise<void> {
    await request.post(
        `/api/v1/knowledge/space/${space_id}/files/${file_id}/tag`,
        { tag_ids }
    );
}

/**
 * Batch append tags to multiple files
 * POST /api/v1/knowledge/space/{space_id}/files/batch-tag
 */
export async function batchUpdateTagsApi(
    space_id: string,
    data: { file_ids: number[]; tag_ids: number[] }
): Promise<void> {
    await request.post(
        `/api/v1/knowledge/space/${space_id}/files/batch-tag`,
        data
    );
}

// ─────────────────────────────────────────────
// API functions — File preview
// ─────────────────────────────────────────────

/**
 * Get file preview content
 */
export async function getFilePreviewApi(space_id: string, file_id: string): Promise<unknown> {
    return request.get(`/api/v1/knowledge/space/${space_id}/files/${file_id}/preview`);
}
