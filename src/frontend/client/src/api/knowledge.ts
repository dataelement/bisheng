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
    HTML = "html",
    TXT = "txt",
    MD = "md",
    WPS = "wps",
    DPS = "dps",
    ET = "et",
    OTHER = "other"
}

/** Space visibility / auth type */
export enum VisibilityType {
    PUBLIC = "public",
    PRIVATE = "private",
    APPROVAL = "approval"
}

/** Sort field */
export enum SortType {
    NAME = "file_name",
    TYPE = "file_type",
    SIZE = "file_size",
    UPDATE_TIME = "update_time"
}

/** Sort values accepted by space list APIs (mine/joined/managed) */
export enum SpaceSortType {
    NAME = "name",
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

    // Used only by the "square explore" UI
    isFollowed?: boolean;
    isPending?: boolean;
    // join | joined | pending | rejected (square list & preview)
    squareStatus?: "join" | "joined" | "pending" | "rejected";

    /** Optional subscription status (e.g. "subscribed") from detail APIs */
    subscriptionStatus?: string;

    /** "department" when bound to a department, "normal" otherwise */
    spaceKind?: "normal" | "department";
    departmentId?: number;
    departmentName?: string;
}

export type SpaceSubscribeStatus = "subscribed" | "pending";

export interface SubscribeSpaceResult {
    status: SpaceSubscribeStatus;
    spaceId: string;
}

/** Space tag entity used by tagging UI */
export interface SpaceTag {
    id: number;
    name: string;
}

/** Space member entity used by member-management dialog */
export interface SpaceMember {
    user_id: number;
    user_name: string;
    user_avatar?: string | null;
    role: "creator" | "admin" | "member";
    groups?: string[];
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
    /** Source of the file, e.g. 'channel' for subscription channel files */
    fileSource?: string;
    /** Path of the existing duplicate file (when status is DUPLICATE) */
    oldFileLevelPath?: string;
    approvalRequestId?: number;
    approvalStatus?: string;
    approvalReason?: string;
    isPendingApproval?: boolean;
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
    follower_num?: number;
    file_num?: number;
    role?: string;
    user_role?: string;
    is_pinned?: boolean;
    create_time?: string;
    update_time?: string;
    tags?: string[];
    is_released?: boolean;
    is_pending?: boolean;
    is_followed?: boolean;
    subscription_status?: string;
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
    remark?: string;
    file_source?: string;
    approval_request_id?: number;
    approval_status?: string;
    approval_reason?: string;
    is_pending_approval?: boolean;
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
        // Some endpoints (e.g. /info) return follower_num/file_num instead of member_count/file_count.
        memberCount: raw.member_count ?? raw.follower_num ?? 0,
        fileCount: raw.file_count ?? raw.file_num ?? 0,
        totalFileCount: raw.total_file_count ?? raw.file_num ?? raw.file_count ?? 0,
        role: (raw.user_role as SpaceRole) || (raw.role as SpaceRole) || SpaceRole.MEMBER,
        isPinned: raw.is_pinned ?? false,
        createdAt: raw.create_time || "",
        updatedAt: raw.update_time || "",
        tags: Array.isArray(raw.tags) ? raw.tags : [],
        isReleased: raw.is_released ?? false,
        isPending: raw.is_pending ?? false,
        isFollowed: raw.is_followed ?? false,
        // Some detail endpoints may carry subscription_status; keep it if present.
        subscriptionStatus:
            (raw as any).subscription_status ??
            (raw as any).subscriptionStatus ??
            undefined,
        spaceKind: (raw as any).space_kind || "normal",
        departmentId: (raw as any).department_id ?? undefined,
        departmentName: (raw as any).department_name ?? undefined,
    };
}

function asArray<T = any>(value: unknown): T[] {
    return Array.isArray(value) ? value as T[] : [];
}

function extractList<T = any>(value: unknown): T[] {
    const payload: any = value ?? {};
    if (Array.isArray(payload)) return payload as T[];
    return asArray<T>(payload?.data ?? payload?.list ?? payload?.records);
}

function extractKnowledgeSpaceList(response: unknown): RawKnowledgeSpace[] {
    const wrapper: any = response ?? {};
    const payload: any = wrapper?.data ?? wrapper;
    const candidates = [
        payload,
        payload?.data,
        payload?.list,
        payload?.records,
        wrapper?.list,
        wrapper?.records,
    ];

    for (const candidate of candidates) {
        if (Array.isArray(candidate)) {
            return candidate;
        }
    }

    return [];
}

/** Derive explicit FileType enum value from a raw child item */
function deriveFileType(raw: any): FileType {
    // Backend: file_type: 0(dir) | 1(file)
    if (raw?.type === "folder" || raw?.file_type === 0 || raw?.file_type === "0") return FileType.FOLDER;

    const fileName = raw?.file_name ?? raw?.name ?? raw?.object_name ?? raw?.path ?? "";
    const ext = String(fileName).split(".").pop()?.toLowerCase() ?? "";
    switch (ext) {
        case "pdf":
            return FileType.PDF;
        case "doc":
            return FileType.DOC;
        case "docx":
            return FileType.DOCX;
        case "xls":
            return FileType.XLS;
        case "xlsx":
            return FileType.XLSX;
        case "ppt":
            return FileType.PPT;
        case "pptx":
            return FileType.PPTX;
        case "jpg":
            return FileType.JPG;
        case "jpeg":
            return FileType.JPEG;
        case "png":
            return FileType.PNG;
        case "html":
            return FileType.HTML;
        case "htm":
            return FileType.HTML;
        case "txt":
            return FileType.TXT;
        case "md":
            return FileType.MD;
        case "wps":
            return FileType.WPS;
        case "dps":
            return FileType.DPS;
        case "et":
            return FileType.ET;
        default:
            return FileType.OTHER;
    }
}

function extractKnowledgeFileError(raw: any): string | undefined {
    const directMessage = raw?.error_message;
    if (typeof directMessage === "string" && directMessage.trim()) {
        return directMessage.trim();
    }

    const remark = raw?.remark;
    if (typeof remark !== "string" || !remark.trim()) {
        return undefined;
    }

    const trimmedRemark = remark.trim();
    try {
        const parsed = JSON.parse(trimmedRemark);
        const nestedMessage =
            parsed?.data?.exception ??
            parsed?.exception ??
            parsed?.message;

        if (typeof nestedMessage === "string" && nestedMessage.trim()) {
            return nestedMessage.trim();
        }

        if (typeof parsed?.status_message === "string" && parsed.status_message.trim()) {
            return parsed.status_message.trim();
        }

        if (typeof parsed?.old_name === "string" || typeof parsed?.new_name === "string") {
            return undefined;
        }
    } catch {
        return trimmedRemark;
    }

    return undefined;
}

/** Map a raw space child (file/folder) to the frontend KnowledgeFile model */
function mapChild(raw: any, spaceId: string): KnowledgeFile {
    // Backend keys in children response usually look like:
    // id, file_name, file_type(0|1), file_level_path, knowledge_id,
    // status(numeric), update_time/create_time, tags(list of {id,name}) for files
    const idVal = raw?.id ?? raw?.file_id ?? raw?.knowledge_file_id ?? "";
    const nameVal = raw?.name ?? raw?.file_name ?? raw?.object_name ?? raw?.file_name ?? raw?.path ?? "";

    const tags: FileTag[] = Array.isArray(raw?.tags)
        ? raw.tags
            .map((t: any) => {
                if (typeof t === "string") return { id: -1, name: t as string };
                const id = t?.id !== undefined && t?.id !== null ? Number(t.id) : -1;
                const name = t?.name !== undefined && t?.name !== null ? String(t.name) : "";
                if (!name) return null;
                return { id, name };
            })
            .filter((v: FileTag | null): v is FileTag => v !== null)
        : [];

    const statusVal = raw?.status;
    const status: FileStatus | undefined =
        typeof statusVal === "number"
            ? mapFileStatus(statusVal)
            : typeof statusVal === "string" && statusVal
                // Backend may return uppercase string like "FAILED" — normalize to lowercase enum value
                ? statusVal.toLowerCase() as FileStatus
                : undefined;

    return {
        id: idVal !== undefined && idVal !== null ? String(idVal) : "",
        name: String(nameVal),
        type: deriveFileType(raw),
        size: raw?.size ?? raw?.file_size,
        status,
        tags,
        path: raw?.path ?? raw?.file_level_path ?? String(nameVal),
        parentId: raw?.parent_id !== undefined && raw?.parent_id !== null ? String(raw.parent_id) : undefined,
        spaceId: raw?.space_id ?? raw?.knowledge_id ?? spaceId,
        createdAt: raw?.create_time ?? "",
        updatedAt: raw?.update_time ?? "",
        thumbnail: raw?.thumbnail ?? raw?.thumbnails,
        errorMessage: extractKnowledgeFileError(raw),
        successFileNum: raw?.success_file_num !== undefined ? Number(raw.success_file_num) : undefined,
        fileNum: raw?.file_num !== undefined ? Number(raw.file_num) : undefined,
        fileSource: raw?.file_source,
        oldFileLevelPath: raw?.old_file_level_path,
        approvalRequestId: raw?.approval_request_id !== undefined ? Number(raw.approval_request_id) : undefined,
        approvalStatus: raw?.approval_status ?? undefined,
        approvalReason: raw?.approval_reason ?? undefined,
        isPendingApproval: Boolean(raw?.is_pending_approval),
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
        case "wps": return FileType.WPS;
        case "dps": return FileType.DPS;
        case "et": return FileType.ET;
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

/** Backend `/children` filter: all statuses except FAILED (3). Used when joined members browse the file list. */
export const SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED: number[] = [1, 2, 4, 5, 6];

/** Backend `/children` filter: SUCCESS (2) only. Used for 广场预览 when user is not an active space member. */
export const SPACE_CHILDREN_STATUS_SUCCESS_ONLY: number[] = [2];

/** Map a raw knowledge file record to the frontend KnowledgeFile model */
function mapRawFile(raw: RawKnowledgeFile): KnowledgeFile {
    const isFolder = raw.file_type === 0;
    return {
        id: String(raw.id),
        name: raw.file_name,
        type: isFolder ? FileType.FOLDER : deriveFileTypeFromName(raw.file_name),
        size: raw.file_size,
        status: isFolder ? undefined : mapFileStatus(raw.status),
        tags: isFolder ? [] : asArray<FileTag>(raw.tags),
        path: raw.object_name || raw.file_name,
        parentId: undefined,
        spaceId: String(raw.knowledge_id),
        createdAt: raw.create_time || "",
        updatedAt: raw.update_time || "",
        thumbnail: raw.thumbnails || undefined,
        errorMessage: extractKnowledgeFileError(raw),
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
    const res = await request.get<ApiResponse<RawKnowledgeSpace[]>>(`/api/v1/knowledge/space/mine`, {
        params: {
            order_by: params?.order_by,
        },
    });
    return extractKnowledgeSpaceList(res).map(mapSpace);
}

/**
 * Get spaces joined by the current user
 */
export async function getJoinedSpacesApi(params?: {
    order_by?: string;
}): Promise<KnowledgeSpace[]> {
    const res = await request.get<ApiResponse<RawKnowledgeSpace[]>>(`/api/v1/knowledge/space/joined`, {
        params: {
            order_by: params?.order_by,
        },
    });
    return extractKnowledgeSpaceList(res).map(mapSpace);
}

/**
 * Get all managed spaces (mine + joined, merged by backend)
 */
export async function getManagedSpacesApi(params?: {
    order_by?: string;
}): Promise<KnowledgeSpace[]> {
    const res = await request.get<ApiResponse<RawKnowledgeSpace[]>>(`/api/v1/knowledge/space/managed`, {
        params: {
            order_by: params?.order_by ?? 'name',
        },
    });
    return extractKnowledgeSpaceList(res).map(mapSpace);
}

/**
 * Get department knowledge spaces the current user belongs to
 */
export async function getDepartmentSpacesApi(params?: {
    order_by?: string;
}): Promise<KnowledgeSpace[]> {
    const res = await request.get<ApiResponse<RawKnowledgeSpace[]>>(`/api/v1/knowledge/space/department`, {
        params: {
            order_by: params?.order_by,
        },
    });
    return extractKnowledgeSpaceList(res).map(mapSpace);
}

/**
 * Get public knowledge square (paginated)
 */
export async function getSquareSpacesApi(params?: {
    order_by?: string;
    sort_by?: string;
    page?: number;
    page_size?: number;
    keyword?: string;
}): Promise<{ data: KnowledgeSpace[]; total: number }> {
    const effectiveSort = params?.sort_by ?? params?.order_by;
    const res = await request.get<ApiResponse<any>>(`/api/v1/knowledge/space/square`, {
        params: {
            ...params,
            sort_by: effectiveSort,
        },
    });
    // Compatible response variants:
    // 1) { status_code, data: { total, page, page_size, data: [...] } }
    // 2) { status_code, data: [...] }
    // 3) { data: [...] }
    // 4) [...]
    const wrapper: any = res ?? {};
    const payload: any = wrapper?.data ?? wrapper ?? {};

    // Backend currently returns:
    // { total, page, page_size, data: [ { space: RawKnowledgeSpace, is_followed, is_pending }, ... ] }
    const rawList: any[] = Array.isArray(payload?.list)
        ? payload.list
        : Array.isArray(payload?.data)
            ? payload.data
            : Array.isArray(payload?.data?.data)
                ? payload.data.data
                : [];

    const mapped: KnowledgeSpace[] = rawList
        .map((item, index) => {
            const itemAny: any = item ?? {};
            const rawAny: any = itemAny?.space ?? itemAny;

            // Derive id/name defensively. Never use String(undefined) -> "undefined".
            const idVal =
                rawAny?.id ??
                rawAny?.space_id ??
                rawAny?.knowledge_space_id ??
                rawAny?.knowledgeSpaceId ??
                rawAny?.knowledge_id ??
                rawAny?.spaceId ??
                rawAny?.knowledgeId ??
                rawAny?.business_id ??
                rawAny?.businessId ??
                itemAny?.id ??
                itemAny?.space_id ??
                itemAny?.knowledge_id ??
                itemAny?.spaceId ??
                itemAny?.knowledgeId ??
                itemAny?.business_id ??
                itemAny?.businessId;

            const id = idVal !== undefined && idVal !== null ? String(idVal) : "";

            const nameVal =
                rawAny?.name ??
                rawAny?.space_name ??
                rawAny?.title ??
                itemAny?.name ??
                itemAny?.space_name ??
                itemAny?.title ??
                "";

            const descriptionVal =
                rawAny?.description ??
                rawAny?.desc ??
                itemAny?.description ??
                itemAny?.desc ??
                undefined;

            const creator =
                itemAny?.user_name ??
                rawAny?.user_name ??
                itemAny?.creator ??
                rawAny?.creator ??
                "";

            const creatorIdVal = rawAny?.user_id ?? itemAny?.user_id ?? rawAny?.userId ?? itemAny?.userId ?? "";

            const authTypeVal = rawAny?.auth_type ?? itemAny?.auth_type ?? rawAny?.authType ?? itemAny?.authType;
            const visibility = (authTypeVal as VisibilityType) || VisibilityType.PRIVATE;

            // status from subscription_status enum. Some square responses expose
            // only is_pending/is_followed, so keep those flags authoritative too.
            const subscriptionStatus = String(
                itemAny?.subscription_status ??
                rawAny?.subscription_status ??
                itemAny?.status ??
                rawAny?.status ??
                ""
            ).toLowerCase();
            const isReleased = Boolean(rawAny?.is_released ?? itemAny?.is_released);
            const isFollowed = Boolean(itemAny?.is_followed ?? rawAny?.is_followed) || subscriptionStatus === "subscribed";
            const isPending = Boolean(itemAny?.is_pending ?? rawAny?.is_pending) || subscriptionStatus === "pending";
            let squareStatus: "join" | "joined" | "pending" | "rejected" = "join";
            if (subscriptionStatus === "rejected") {
                squareStatus = "rejected";
            } else if (isFollowed) {
                squareStatus = "joined";
            } else if (isPending) {
                squareStatus = "pending";
            }

            const fileNum = itemAny?.file_num ?? rawAny?.file_num ?? rawAny?.fileNum ?? itemAny?.fileNum ?? 0;
            const followerNum =
                itemAny?.follower_num ?? rawAny?.follower_num ?? rawAny?.followerNum ?? itemAny?.followerNum ?? 0;

            const iconOrAvatar = itemAny?.avatar ?? rawAny?.avatar ?? rawAny?.icon ?? itemAny?.icon ?? "";

            const createdAt = rawAny?.create_time ?? itemAny?.create_time ?? "";
            const updatedAt = rawAny?.update_time ?? itemAny?.update_time ?? "";

            const safeId = id || `${creatorIdVal || "space"}-${nameVal || "unknown"}-${index}`;

            return {
                id: safeId,
                name: String(nameVal ?? ""),
                description: descriptionVal !== undefined ? String(descriptionVal) : undefined,
                icon: iconOrAvatar,
                visibility,
                creator,
                creatorId: creatorIdVal !== undefined && creatorIdVal !== null ? String(creatorIdVal) : "",
                memberCount: Number(followerNum ?? 0),
                fileCount: Number(fileNum ?? 0),
                totalFileCount: Number(fileNum ?? 0),
                role: SpaceRole.MEMBER,
                isPinned: false,
                createdAt: createdAt ? String(createdAt) : "",
                updatedAt: updatedAt ? String(updatedAt) : "",
                tags: [],
                isReleased,
                isFollowed,
                isPending,
                squareStatus,
                subscriptionStatus: subscriptionStatus || undefined,
            };
        })
        // Keep entries without id but avoid "undefined" key; drawer won't open for them.
        .map((s) => s);

    return {
        data: mapped,
        total: Number(payload?.total ?? payload?.data?.total ?? 0),
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
    const res: any = await request.post(`/api/v1/knowledge/space`, data);
    const statusCode = res?.status_code ?? res?.code ?? 200;
    if (statusCode !== 200) {
        throw new Error(res?.status_message || res?.message || "createSpaceApi failed");
    }
    const raw = res?.data;
    if (!raw || raw?.id === undefined || raw?.id === null) {
        throw new Error("createSpaceApi: missing data");
    }
    return mapSpace({ ...raw, user_role: SpaceRole.CREATOR });
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
    const res: any = await request.get<ApiResponse<RawKnowledgeSpace>>(
        `/api/v1/knowledge/space/${space_id}/info`
    );
    const statusCode = res?.status_code ?? res?.code;
    if (statusCode && statusCode !== 200) {
        throw new Error(res?.status_message || res?.message || "getSpaceInfoApi failed");
    }
    const raw = res?.data;
    if (!raw || raw?.id === undefined || raw?.id === null) {
        throw new Error("getSpaceInfoApi: missing data");
    }
    return mapSpace(raw);
}

/**
 * Get members of a space
 */
export async function getSpaceMembersApi(space_id: string): Promise<{ data: SpaceMember[]; total: number }> {
    const res: any = await request.get(`/api/v1/knowledge/space/${space_id}/members`);
    // Compatible response variants:
    // 1) { status_code, data: { data: [...], total } }
    // 2) { status_code, data: [...] }
    // 3) { data: [...] }
    // 4) [...]
    const wrapper = res ?? {};
    const payload = wrapper?.data ?? wrapper;
    const list = Array.isArray(payload)
        ? payload
        : Array.isArray(payload?.data)
            ? payload.data
            : Array.isArray(payload?.members)
                ? payload.members
                : [];

    const mapped: SpaceMember[] = list.map((m: any) => ({
        user_id: Number(m?.user_id ?? 0),
        user_name: String(m?.user_name ?? ""),
        user_avatar: m?.user_avatar ?? m?.avatar ?? null,
        role: String(m?.user_role ?? m?.role ?? "member") as SpaceMember["role"],
        groups: asArray(m?.user_groups ?? m?.groups)
            .map((g: any) => String(g?.name ?? g?.group_name ?? g))
            .filter(Boolean),
    }));

    return {
        data: mapped,
        total: Number(payload?.total ?? wrapper?.total ?? mapped.length ?? 0),
    };
}

/**
 * Update space member role
 * PUT /api/v1/knowledge/space/{space_id}/members/role
 */
export async function updateSpaceMemberRoleApi(space_id: string, body: {
    user_id: number;
    role: "admin" | "member";
}): Promise<void> {
    await request.put(`/api/v1/knowledge/space/${space_id}/members/role`, body);
}

/**
 * Delete space member
 * DELETE /api/v1/knowledge/space/{space_id}/members
 */
export async function removeSpaceMemberApi(space_id: string, user_id: number): Promise<void> {
    await request.deleteWithOptions(`/api/v1/knowledge/space/${space_id}/members`, {
        data: { user_id },
    });
}

/**
 * Get tags for a knowledge space.
 * Backend: GET /api/v1/knowledge/space/{space_id}/tag
 */
export async function getSpaceTagsApi(space_id: string): Promise<SpaceTag[]> {
    const res = await request.get<ApiResponse<SpaceTag[]>>(`/api/v1/knowledge/space/${space_id}/tag`);
    return extractList<SpaceTag>(res?.data);
}

/**
 * Add a new space tag.
 * Backend: POST /api/v1/knowledge/space/{space_id}/tag
 */
export async function addSpaceTagApi(space_id: string, tag_name: string): Promise<SpaceTag> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const res = (await request.post(`/api/v1/knowledge/space/${space_id}/tag`, { tag_name })) as any;
    // Handle both flat { id, name } and wrapped { data: { id, name } } responses
    const tag = res?.data?.id !== undefined ? res.data : res?.data?.data;
    return tag as SpaceTag;
}

/**
 * Delete a space tag.
 * Backend: DELETE /api/v1/knowledge/space/{space_id}/tag
 */
export async function deleteSpaceTagApi(space_id: string, tag_id: number): Promise<void> {
    await request.deleteWithOptions(`/api/v1/knowledge/space/${space_id}/tag`, {
        data: { tag_id },
    });
}

/**
 * Overwrite tags for a single file.
 * Backend: POST /api/v1/knowledge/space/{space_id}/files/{file_id}/tag
 */
export async function updateFileTagsApi(space_id: string, file_id: string, tag_ids: number[]): Promise<void> {
    await request.post(`/api/v1/knowledge/space/${space_id}/files/${file_id}/tag`, { tag_ids });
}

/**
 * Batch add tags for files.
 * Backend: POST /api/v1/knowledge/space/{space_id}/files/batch-tag
 */
export async function batchUpdateTagsApi(
    space_id: string,
    data: { file_ids: number[]; tag_ids: number[] }
): Promise<void> {
    await request.post(`/api/v1/knowledge/space/${space_id}/files/batch-tag`, data);
}

/**
 * Subscribe to a space
 * POST /api/v1/knowledge/space/{space_id}/subscribe
 */
export async function subscribeSpaceApi(space_id: string): Promise<SubscribeSpaceResult> {
    const res = await request.post(`/api/v1/knowledge/space/${space_id}/subscribe`) as any;
    if (res?.status_code && res.status_code !== 200) {
        const msg =
            (res as any)?.status_message ||
            (res as any)?.message ||
            (res as any)?.msg ||
            "subscribe space failed";
        throw new Error(msg);
    }
    const payload = res?.data ?? res ?? {};
    const status = String(payload?.status ?? "").toLowerCase();
    if (status !== "subscribed" && status !== "pending") {
        throw new Error("subscribe space failed: missing subscription status");
    }
    return {
        status,
        spaceId: String(payload?.space_id ?? payload?.spaceId ?? space_id),
    };
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
    return extractList(data).map((item: any) => ({
        id: String(item.id),
        name: item.name || item.file_name || String(item.id),
    }));
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
    const res = await request.get<ApiResponse<{ data: RawSpaceChild[]; total: number }>>(
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
            paramsSerializer: request.paramsSerializer,
        }
    );
    const payload: any = res?.data ?? {};
    const list = extractList<RawSpaceChild>(payload);
    return {
        data: list.map(raw => mapChild(raw, space_id)),
        total: Number(payload?.total ?? list.length),
    };
}

/**
 * Search children (folders and files) within a space.
 * Backend: GET /api/v1/knowledge/space/{space_id}/search
 */
export async function searchSpaceChildrenApi(params: {
    space_id: string;
    parent_id?: string;
    keyword?: string;
    tag_ids?: number[];
    page?: number;
    page_size?: number;
    order_field?: string;
    order_sort?: string;
    file_status?: number[];
}): Promise<{ data: KnowledgeFile[]; total: number }> {
    const { space_id, ...queryParams } = params;
    if (!space_id) return { data: [], total: 0 };

    const res = await request.get<ApiResponse<{ data: RawSpaceChild[]; total: number }>>(
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
            paramsSerializer: request.paramsSerializer,
        }
    );

    const payload: any = res?.data ?? {};
    const list = extractList<RawSpaceChild>(payload);
    return {
        data: list.map(raw => mapChild(raw, space_id)),
        total: Number(payload?.total ?? list.length),
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
    ) as ApiResponse<RawSpaceChild> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw new Error(res.status_message || res.message || res.msg || "create folder failed");
    }
    if (!res?.data) {
        throw new Error("create folder failed: missing data");
    }
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
    const res = await request.put(
        `/api/v1/knowledge/space/${space_id}/folders/${folder_id}`,
        { name }
    ) as ApiResponse<RawSpaceChild> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw new Error(res.status_message || res.message || res.msg || "rename folder failed");
    }
}

/**
 * Delete a folder (recursively deletes all children)
 */
export async function deleteFolderApi(space_id: string, folder_id: string): Promise<void> {
    const res = await request.delete(
        `/api/v1/knowledge/space/${space_id}/folders/${folder_id}`
    ) as ApiResponse<null> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw new Error(res.status_message || res.message || res.msg || "delete folder failed");
    }
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
    const res = await request.postMultiPart(`/api/v1/knowledge/upload/${space_id}`, formData) as ApiResponse<UploadFileResponse> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw new Error(res.status_message || res.message || res.msg || "upload file failed");
    }
    if (!res?.data?.file_path) {
        throw new Error("upload file failed: missing file path");
    }
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
        data,
        { showError: true }
    ) as ApiResponse<RawSpaceChild[]> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw new Error(res.status_message || res.message || res.msg || "register files failed");
    }
    const payload: any = res?.data ?? {};
    const list = extractList<RawSpaceChild>(payload);
    return list.map(raw => {
        const file = mapChild(raw, space_id);
        // Preserve raw object for status 3 (duplicate) so retry API can use it
        if (raw?.status === 3) {
            (file as any)._raw = raw;
        }
        return file;
    });
}

/**
 * Add article(s) to a knowledge space folder
 * POST /api/v1/channel/manager/articles/add_to_knowledge_space
 */
export async function addArticleToKnowledgeApi(
    knowledge_id: string,
    article_ids: string[],
    parent_id?: string | null,
    force_replace?: boolean
): Promise<any> {
    const res = await request.post(`/api/v1/channel/manager/articles/add_to_knowledge_space`, {
        knowledge_id: Number(knowledge_id),
        article_ids,
        parent_id: parent_id ? Number(parent_id) : null,
        ...(force_replace ? { force_replace: true } : {}),
    }, { showError: true });
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw { response: { data: res } };
    }
    return res;
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
    const res = await request.post(
        `/api/v1/knowledge/space/${space_id}/files/batch-delete`,
        data
    ) as ApiResponse<null> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw new Error(res.status_message || res.message || res.msg || "batch delete failed");
    }
}

/**
 * Batch download files and/or folders (returns a download URL or triggers download)
 */
export async function batchDownloadApi(
    space_id: string,
    data: { file_ids?: number[]; folder_ids?: number[] }
): Promise<string> {
    const res: any = await request.post(
        `/api/v1/knowledge/space/${space_id}/files/batch-download`,
        data
    );
    if (res?.status_code !== undefined && res.status_code !== 200) {
        throw new Error(res.status_message || res.message || res.msg || "batch download failed");
    }
    // Response: { status_code, data: { url: "/tmp-dir/..." } }
    return res?.data?.url ?? res?.url ?? "";
}

/**
 * Retry duplicate files (replace existing)
 * POST /api/v1/knowledge/space/{space_id}/files/retry
 * @param file_objs - raw file objects from addFilesApi response where status === 3
 */
export async function retryDuplicateFilesApi(
    space_id: string,
    file_objs: any[]
): Promise<void> {
    await request.post(`/api/v1/knowledge/space/${space_id}/files/retry`, { file_objs });
}

/**
 * Batch retry failed files/folders
 * POST /api/v1/knowledge/space/{space_id}/files/batch-retry
 */
export async function batchRetryApi(
    space_id: string,
    file_ids: number[]
): Promise<void> {
    await request.post(`/api/v1/knowledge/space/${space_id}/files/batch-retry`, { file_ids });
}

// ─────────────────────────────────────────────
// API functions — File preview
// ─────────────────────────────────────────────

/**
 * Get file preview URL
 * Returns { original_url, preview_url } — prefer preview_url, fallback to original_url
 */
export async function getFilePreviewApi(
    space_id: string,
    file_id: string
): Promise<{ original_url: string; preview_url: string }> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const res = await request.get<any>(`/api/v1/knowledge/space/${space_id}/files/${file_id}/preview`);
    const data = res?.data ?? res;
    return {
        original_url: data?.original_url ?? "",
        preview_url: data?.preview_url ?? "",
    };
}
