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
    QUEUED = "queued",
    PROCESSING = "processing",
    SUCCESS = "success",
    FAILED = "failed",
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
    NAME = "name",
    TYPE = "type",
    SIZE = "size",
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
export interface KnowledgeFile {
    id: string;
    name: string;
    type: FileType;
    size?: number;
    status?: FileStatus;
    tags: string[];
    path: string;
    parentId?: string;           // mapped from parent_id
    spaceId: string;
    createdAt: string;           // mapped from create_time
    updatedAt: string;           // mapped from update_time
    thumbnail?: string;
    errorMessage?: string;
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
        role: (raw.role as SpaceRole) || SpaceRole.MEMBER,
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
 */
export async function getSquareSpacesApi(params?: {
    order_by?: string;
    page?: number;
    page_size?: number;
}): Promise<{ data: KnowledgeSpace[]; total: number }> {
    const res = await request.get<ApiResponse<{ list: RawKnowledgeSpace[]; total: number }>>(
        `/api/v1/knowledge/space/square`,
        { params }
    );
    return {
        data: (res?.data?.list || []).map(mapSpace),
        total: res?.data?.total ?? 0,
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
}): Promise<{ data: KnowledgeFile[]; total: number }> {
    const { space_id, ...queryParams } = params;
    if (!space_id) return { data: [], total: 0 };
    const res = await request.get<ApiResponse<{ list: RawSpaceChild[]; total: number }>>(
        `/api/v1/knowledge/space/${space_id}/children`,
        {
            params: {
                parent_id: queryParams.parent_id,
                page: queryParams.page,
                page_size: queryParams.page_size,
            }
        }
    );
    return {
        data: (res?.data?.list || []).map(raw => mapChild(raw, space_id)),
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
    ) as ApiResponse<RawSpaceChild[]>;
    return (res?.data || []).map(raw => mapChild(raw, space_id));
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
// API functions — File preview
// ─────────────────────────────────────────────

/**
 * Get file preview content
 */
export async function getFilePreviewApi(space_id: string, file_id: string): Promise<unknown> {
    return request.get(`/api/v1/knowledge/space/${space_id}/files/${file_id}/preview`);
}
