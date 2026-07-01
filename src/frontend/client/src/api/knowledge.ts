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
    TIMEOUT = "timeout",
    VIOLATION = "violation"
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
    AUDIO = "audio",
    VIDEO = "video",
    WEB = "web",
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
    autoTagEnabled?: boolean;
    autoTagLibraryId?: number | null;
    /** "library" when bound to a tenant tag library, "custom" when backed by per-space tags */
    autoTagMode?: "library" | "custom";
    /** Populated only when autoTagMode === "custom" */
    autoTagCustomTags?: string[] | null;

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
    approvalEnabled?: boolean;
    sensitiveCheckEnabled?: boolean;
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

export interface SensitiveWordHit {
    word: string;
    count: number;
}

export interface KnowledgeFileSensitiveCheck {
    autoReply?: string;
    hits: SensitiveWordHit[];
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
    sensitiveCheck?: KnowledgeFileSensitiveCheck;
    /** Number of successfully parsed files (folders only) */
    successFileNum?: number;
    /** Total number of files (folders only) */
    fileNum?: number;
    /** Number of files in PROCESSING/WAITING/REBUILDING (folders only) */
    processingFileNum?: number;
    /** Source of the file, e.g. 'channel' for subscription channel files */
    fileSource?: string;
    /** Path of the existing duplicate file (when status is DUPLICATE) */
    oldFileLevelPath?: string;
    approvalRequestId?: number;
    approvalStatus?: string;
    approvalReason?: string;
    fileEncoding?: string | null;        // mapped from file_encoding
    isPendingApproval?: boolean;
    version_no?: number;          // primary version number; absent for folders / legacy files
    is_multi_version?: boolean;   // true when the document has >=2 versions
    has_similar?: boolean;        // true when similar_status === 1 (pending review)
    user_name?: string;           // mapped from user_name — original uploader of this file
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
    auto_tag_enabled?: boolean;
    auto_tag_library_id?: number | null;
    auto_tag_mode?: "library" | "custom";
    auto_tag_custom_tags?: string[] | null;
    is_pending?: boolean;
    is_followed?: boolean;
    subscription_status?: string;
}

export interface KnowledgeSpaceTagLibraryListItem {
    id: number;
    name: string;
    description?: string | null;
    tag_count: number;
    is_builtin: boolean;
}

export interface KnowledgeSpaceTagLibraryPage {
    data: KnowledgeSpaceTagLibraryListItem[];
    total: number;
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
    processing_file_num?: number;
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
        autoTagEnabled: raw.auto_tag_enabled ?? false,
        autoTagLibraryId: raw.auto_tag_library_id ?? null,
        autoTagMode: raw.auto_tag_mode ?? (raw.auto_tag_custom_tags ? "custom" : "library"),
        autoTagCustomTags: Array.isArray(raw.auto_tag_custom_tags)
            ? raw.auto_tag_custom_tags
            : null,
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
        approvalEnabled:
            (raw as any).approval_enabled !== undefined
                ? Boolean((raw as any).approval_enabled)
                : undefined,
        sensitiveCheckEnabled:
            (raw as any).sensitive_check_enabled !== undefined
                ? Boolean((raw as any).sensitive_check_enabled)
                : undefined,
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
    if (raw?.file_source === "web_link") return FileType.WEB;
    if (raw?.file_source === "audio_transcript") return FileType.AUDIO;
    if (raw?.file_source === "video_transcript") return FileType.VIDEO;

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
        case "mp3":
        case "wav":
        case "m4a":
        case "aac":
        case "flac":
        case "ogg":
            return FileType.AUDIO;
        case "mp4":
        case "mov":
        case "avi":
        case "mkv":
        case "webm":
            return FileType.VIDEO;
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

function formatSensitiveViolationMessage(hits: any[]): string {
    const words = hits
        .map((item) => String(item?.word ?? "").trim())
        .filter(Boolean)
        .filter((word, index, arr) => arr.indexOf(word) === index);

    if (!words.length) {
        return "您上传的文件包含违规内容，请修改后重试";
    }

    return `您上传的文件包含违规内容：{${words.join(",")}}，请修改后重试`;
}

export function extractKnowledgeFileError(raw: any): string | undefined {
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
        if (parsed?.reason === "sensitive_check") {
            return formatSensitiveViolationMessage(Array.isArray(parsed?.hits) ? parsed.hits : []);
        }

        const statusMessage = parsed?.status_message;
        if (typeof statusMessage === "string" && statusMessage.trim()) {
            const replacedMessage = statusMessage.replace(/\{([^{}]+)\}/g, (placeholder, key) => {
                const value = parsed?.data?.data?.[key];
                if (value === undefined || value === null) {
                    return placeholder;
                }
                return String(value);
            }).trim();

            if (replacedMessage && replacedMessage !== statusMessage.trim()) {
                return replacedMessage;
            }
        }

        const nestedMessage =
            parsed?.data?.exception ??
            parsed?.exception ??
            parsed?.message;

        if (typeof nestedMessage === "string" && nestedMessage.trim()) {
            return nestedMessage.trim();
        }

        if (typeof statusMessage === "string" && statusMessage.trim()) {
            return statusMessage.trim();
        }

        if (typeof parsed?.old_name === "string" || typeof parsed?.new_name === "string") {
            return undefined;
        }
    } catch {
        return trimmedRemark;
    }

    return undefined;
}

export function extractKnowledgeFileSensitiveCheck(raw: any): KnowledgeFileSensitiveCheck | undefined {
    const remark = raw?.remark;
    if (typeof remark !== "string" || !remark.trim()) {
        return undefined;
    }
    try {
        const parsed = JSON.parse(remark.trim());
        if (parsed?.reason !== "sensitive_check") {
            return undefined;
        }
        const hits = Array.isArray(parsed?.hits)
            ? parsed.hits
                .map((item: any) => ({
                    word: String(item?.word ?? ""),
                    count: Number(item?.count ?? 0),
                }))
                .filter((item: SensitiveWordHit) => item.word && item.count > 0)
            : [];
        return {
            autoReply: typeof parsed?.auto_reply === "string" ? parsed.auto_reply : undefined,
            hits,
        };
    } catch {
        return undefined;
    }
}

/** Display title for imported web links. */
function ensureWebLinkHtmlName(name: string): string {
    const trimmed = name.trim().replace(/\.md$/i, "").trim();
    if (!trimmed) return "";
    return trimmed.toLowerCase().endsWith(".html") ? trimmed : `${trimmed}.html`;
}

export function resolveWebLinkDisplayName(
    fileName: string,
    userMetadata?: Record<string, unknown>,
): string {
    const stem = ensureWebLinkHtmlName(fileName);
    if (stem) return stem;
    const webTitle = typeof userMetadata?.web_title === "string" ? userMetadata.web_title.trim() : "";
    return ensureWebLinkHtmlName(webTitle) || "web-link.html";
}

/** Normalize user-entered web link display name to persisted file_name. */
export function toWebLinkFileName(displayName: string): string {
    return ensureWebLinkHtmlName(displayName);
}

export function isWebLinkKnowledgeFile(file: Pick<KnowledgeFile, "fileSource" | "type">): boolean {
    return file.fileSource === "web_link" || file.type === FileType.WEB;
}

/** Map a raw space child (file/folder) to the frontend KnowledgeFile model */
function mapChild(raw: any, spaceId: string): KnowledgeFile {
    // Backend keys in children response usually look like:
    // id, file_name, file_type(0|1), file_level_path, knowledge_id,
    // status(numeric), update_time/create_time, tags(list of {id,name}) for files
    const idVal = raw?.id ?? raw?.file_id ?? raw?.knowledge_file_id ?? "";
    const rawName = raw?.name ?? raw?.file_name ?? raw?.object_name ?? raw?.file_name ?? raw?.path ?? "";
    const userMetadata = raw?.user_metadata ?? raw?.userMetadata ?? {};
    const nameVal = raw?.file_source === "web_link"
        ? resolveWebLinkDisplayName(String(rawName), userMetadata)
        : rawName;

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
        sensitiveCheck: extractKnowledgeFileSensitiveCheck(raw),
        successFileNum: raw?.success_file_num !== undefined ? Number(raw.success_file_num) : undefined,
        fileNum: raw?.file_num !== undefined ? Number(raw.file_num) : undefined,
        processingFileNum: raw?.processing_file_num !== undefined ? Number(raw.processing_file_num) : undefined,
        fileSource: raw?.file_source,
        oldFileLevelPath: raw?.old_file_level_path,
        approvalRequestId: raw?.approval_request_id !== undefined ? Number(raw.approval_request_id) : undefined,
        approvalStatus: raw?.approval_status ?? undefined,
        approvalReason: raw?.approval_reason ?? undefined,
        isPendingApproval: Boolean(raw?.is_pending_approval),
        fileEncoding: raw?.file_encoding ?? null,
        version_no: raw?.version_no !== undefined && raw?.version_no !== null ? Number(raw.version_no) : undefined,
        is_multi_version: Boolean(raw?.is_multi_version),
        has_similar: Boolean(raw?.has_similar),
        user_name: raw?.user_name ?? undefined,
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
        case "mp3":
        case "wav":
        case "m4a":
        case "aac":
        case "flac":
        case "ogg":
            return FileType.AUDIO;
        case "mp4":
        case "mov":
        case "avi":
        case "mkv":
        case "webm":
            return FileType.VIDEO;
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
        case 7: return FileStatus.VIOLATION;
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
        case FileStatus.VIOLATION: return 7;
        default: return 0;
    }
}

/** Backend `/children` filter for members: keep violation visible, exclude generic failed files. */
export const SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED: number[] = [1, 2, 4, 5, 6, 7];

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
        sensitiveCheck: extractKnowledgeFileSensitiveCheck(raw),
        successFileNum: raw.success_file_num,
        fileNum: raw.file_num,
        processingFileNum: raw.processing_file_num,
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
    auto_tag_enabled?: boolean;
    auto_tag_library_id?: number | null;
    auto_tag_custom_tags?: string[] | null;
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
        auto_tag_enabled?: boolean;
        auto_tag_library_id?: number | null;
        auto_tag_custom_tags?: string[] | null;
    }
): Promise<KnowledgeSpace> {
    if (!space_id) throw new Error("space_id is required");
    const res = await request.put(`/api/v1/knowledge/space/${space_id}`, data) as ApiResponse<RawKnowledgeSpace>;
    return mapSpace(res.data);
}

export interface KnowledgeSpaceTagLibraryDetail extends KnowledgeSpaceTagLibraryListItem {
    tags: string[];
}

/** Fetch a single tag library with its full tag list, used for the preview chips. */
export async function getKnowledgeSpaceTagLibraryDetailApi(
    library_id: number,
): Promise<KnowledgeSpaceTagLibraryDetail> {
    const res = await request.get<ApiResponse<KnowledgeSpaceTagLibraryDetail>>(
        `/api/v1/knowledge/space/tag-libraries/${library_id}`,
    );
    const payload: any = (res as any)?.data ?? res;
    return {
        id: Number(payload?.id),
        name: String(payload?.name ?? ""),
        description: payload?.description ?? null,
        tag_count: Number(payload?.tag_count ?? 0),
        is_builtin: Boolean(payload?.is_builtin),
        tags: Array.isArray(payload?.tags) ? payload.tags : [],
    };
}

export async function getKnowledgeSpaceTagLibrariesApi(params?: {
    page?: number;
    page_size?: number;
    keyword?: string;
}): Promise<KnowledgeSpaceTagLibraryPage> {
    const res = await request.get<ApiResponse<KnowledgeSpaceTagLibraryPage>>(
        `/api/v1/knowledge/space/tag-libraries`,
        { params }
    );
    const payload: any = (res as any)?.data ?? res;
    return {
        data: Array.isArray(payload?.data) ? payload.data : [],
        total: Number(payload?.total ?? 0),
    };
}

/**
 * Whether the knowledge-space auto-tag UI is enabled for the current tenant.
 * Read-only; backed by the workstation knowledge-space config (with root→tenant
 * inheritance). Returns { visible: false } when not configured.
 */
export async function getKnowledgeSpaceAutoTagVisibilityApi(): Promise<{ visible: boolean }> {
    const res = await request.get<ApiResponse<{ visible: boolean }>>(
        `/api/v1/knowledge/space/auto-tag-visibility`
    );
    const payload: any = (res as any)?.data ?? res;
    return { visible: Boolean(payload?.visible) };
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
        const err: any = new Error(msg);
        // Surface the backend error code so callers can branch (e.g. 18032
        // = join-limit reached → localized hint).
        err.status_code = res.status_code;
        throw err;
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
export async function unsubscribeSpaceApi(space_id: string): Promise<any> {
    return await request.post(`/api/v1/knowledge/space/${space_id}/unsubscribe`);
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

// ─────────────────────────────────────────────
// API functions — Directory tree (folders only)
// ─────────────────────────────────────────────

/** Folder node returned by the directory-tree API (file_type=0 filter) */
export interface KnowledgeFolderNode {
    id: number;
    file_name: string;
    /** 0 = directory, 1 = file */
    file_type: 0 | 1;
    file_size: number | null;
    created_at?: string;
    updated_at?: string;
}

/**
 * List direct-child folders of a space (file_type=0).
 * Used exclusively by the KnowledgeTree left-side panel.
 */
export async function listKnowledgeFolders(params: {
    space_id: string | number;
    parent_id?: string | number | null;
    /**
     * Status filter — must mirror what the right-side file panel sends so the
     * tree and the panel stay consistent. For MEMBER-role users this should be
     * SPACE_CHILDREN_STATUS_NUMS_EXCLUDE_FAILED; omit for admins/creators.
     */
    file_status?: number[];
}): Promise<{ items: KnowledgeFolderNode[]; total: number }> {
    if (!params.space_id) return { items: [], total: 0 };
    const res = await request.get<any>(
        `/api/v1/knowledge/space/${params.space_id}/children`,
        {
            params: {
                parent_id: params.parent_id != null && params.parent_id !== "" ? params.parent_id : undefined,
                file_type: 0,
                page: 1,
                page_size: 200,
                order_field: "file_name",
                order_sort: "asc",
                file_status: params.file_status?.length ? params.file_status : undefined,
            },
            paramsSerializer: request.paramsSerializer,
        }
    );
    const payload: any = res?.data ?? res ?? {};
    const list: any[] = Array.isArray(payload)
        ? payload
        : Array.isArray(payload?.data)
            ? payload.data
            : Array.isArray(payload?.list)
                ? payload.list
                : [];
    const total = Number(payload?.total ?? list.length);
    const items: KnowledgeFolderNode[] = list.map((raw: any) => ({
        id: Number(raw?.id ?? 0),
        file_name: String(raw?.name ?? raw?.file_name ?? ""),
        file_type: (raw?.file_type === 0 || raw?.type === "folder") ? 0 : 1,
        file_size: raw?.file_size ?? raw?.size ?? null,
        created_at: raw?.create_time,
        updated_at: raw?.update_time,
    }));
    return { items, total };
}

/**
 * Get items (folders and files) under a space directory
 * If parent_id is omitted, returns root-level items
 */
// F027: cursor-based pagination.
//   request:  { space_id, parent_id?, cursor?, page_size, order_field, order_sort, file_status? }
//   response: { data: KnowledgeFile[], page_size, has_more, next_cursor }
//   The legacy `total` / `page` fields are gone (spec AC-03).
export async function getSpaceChildrenApi(params: {
    space_id: string;
    parent_id?: string;
    cursor?: string | null;
    page_size?: number;
    order_field?: string;
    order_sort?: string;
    file_status?: number[];
}): Promise<{ data: KnowledgeFile[]; page_size: number; has_more: boolean; next_cursor: string | null }> {
    const { space_id, ...queryParams } = params;
    if (!space_id) {
        return { data: [], page_size: queryParams.page_size ?? 20, has_more: false, next_cursor: null };
    }
    const res = await request.get<ApiResponse<any>>(
        `/api/v1/knowledge/space/${space_id}/children`,
        {
            params: {
                parent_id: queryParams.parent_id,
                cursor: queryParams.cursor || undefined,
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
        page_size: Number(payload?.page_size ?? queryParams.page_size ?? 20),
        has_more: !!payload?.has_more,
        next_cursor: payload?.next_cursor ?? null,
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
}): Promise<{ data: KnowledgeFile[]; has_more: boolean }> {
    const { space_id, ...queryParams } = params;
    if (!space_id) return { data: [], has_more: false };

    // F040: the backend batch-scans the keyword-search candidate set and returns
    // `has_more` directly instead of an exact post-filter `total` (which would
    // require materialising every match). Pagination is driven off `has_more`.
    const res = await request.get<ApiResponse<{ data: RawSpaceChild[]; has_more: boolean }>>(
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
        has_more: Boolean(payload?.has_more),
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
    file: File,
    /**
     * Explicit filename for the multipart part. Defaults to `file.name`.
     * Pass this when uploading Files from a `<input webkitdirectory>` picker —
     * Chromium otherwise uses `file.webkitRelativePath` (e.g. `Docs/a.pdf`)
     * as the multipart filename, which the backend persists verbatim.
     */
    filename?: string,
): Promise<UploadFileResponse> {
    const formData = new FormData();
    formData.append("file", file, filename ?? file.name);
    const res = await request.postMultiPart(`/api/v1/knowledge/upload/${space_id}`, formData) as ApiResponse<UploadFileResponse> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        // Preserve status_code and data so the caller can render the localized
        // backend message via i18n (e.g. api_errors.19403 with used_gb/quota_gb)
        // instead of falling through to a generic "upload failed" toast.
        const err = new Error(res.status_message || res.message || res.msg || "upload file failed");
        (err as any).statusCode = res.status_code;
        (err as any).errorData = res.data;
        throw err;
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

export async function importWebLinkApi(
    space_id: string,
    data: { url: string; title?: string; parent_id?: number | null; file_category_code?: string; overwrite?: boolean }
): Promise<KnowledgeFile> {
    const res = await request.post(
        `/api/v1/knowledge/space/${space_id}/web-links`,
        data,
        { showError: false } as any
    ) as ApiResponse<RawSpaceChild> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        const error = new Error(res.status_message || res.message || res.msg || "import web link failed") as Error & {
            status_code?: number;
            status_message?: string;
        };
        error.status_code = res.status_code;
        error.status_message = res.status_message;
        throw error;
    }
    return mapChild(res.data, space_id);
}

/** One file of a folder upload: uploaded body path + its path inside the picked folder. */
export interface FolderUploadItemPayload {
    file_path: string;
    relative_path: string;
    size: number;
}

/**
 * F034 §5.5: register a whole folder (nested) in one batch — the backend
 * rebuilds the directory tree from each item's relative_path.
 * POST /api/v1/knowledge/space/{space_id}/folders/upload
 *
 * `skip403Redirect` routes batch rejections (18011 depth / 18012 dup folder /
 * 18024 user quota / 18025 count / 19403 tenant quota) through the unified
 * interceptor: api_errors.<code> is translated, toasted (AC-32), and the
 * promise rejects so the caller's catch fires.
 */
export async function uploadFolderApi(
    space_id: string,
    data: { parent_id?: number | null; items: FolderUploadItemPayload[] }
): Promise<KnowledgeFile[]> {
    const res = await request.post(
        `/api/v1/knowledge/space/${space_id}/folders/upload`,
        data,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { skip403Redirect: true } as any,
    ) as ApiResponse<RawSpaceChild[]>;
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
// API functions — Move (F034)
// ─────────────────────────────────────────────

export interface MoveItemInput {
    id: string;
    type: "file" | "folder";
}

export interface MovedEntry {
    id: number;
    type: "file" | "folder";
    /** Source parent folder id (null = space root); used for same-space undo. */
    old_parent_id: number | null;
    cross_space: boolean;
}

/** Reason a single item could not be moved (per-item, batch-safe). */
export type MoveInvalidReason =
    | "no_permission"
    | "into_self"
    | "into_subtree"
    | "into_current_parent"
    | "depth_exceeded"
    | "name_conflict";

export interface InvalidEntry {
    id: number;
    type: "file" | "folder";
    name: string;
    reason: MoveInvalidReason;
}

export interface MoveResult {
    moved: MovedEntry[];
    invalid: InvalidEntry[];
}

/**
 * Move files/folders within a space or across spaces.
 * target_space_id === space_id ⇒ same-space move; otherwise cross-space.
 * Business errors (18033/18040/18041) reject with `.status_code` for branching.
 */
export async function moveFilesApi(
    space_id: string,
    params: {
        items: MoveItemInput[];
        target_space_id: string;
        target_folder_id?: string | null;
        skip_invalid?: boolean;
    }
): Promise<MoveResult> {
    const res = (await request.post(`/api/v1/knowledge/space/${space_id}/files/move`, {
        items: params.items.map((i) => ({ id: Number(i.id), type: i.type })),
        target_space_id: Number(params.target_space_id),
        target_folder_id:
            params.target_folder_id != null ? Number(params.target_folder_id) : null,
        skip_invalid: params.skip_invalid ?? false,
    })) as ApiResponse<MoveResult> & { message?: string; msg?: string };
    if (res?.status_code !== undefined && res.status_code !== 200) {
        const err = new Error(
            res.status_message || res.message || res.msg || "move failed"
        ) as Error & { status_code?: number };
        err.status_code = res.status_code;
        throw err;
    }
    return res.data;
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
 * File preview URLs and source metadata.
 */
export interface KnowledgeFilePreview {
    original_url: string;
    preview_url: string;
    file_source: string;
    source_url: string;
    final_url: string;
    web_title: string;
    media_kind: string;
    html_preview_url: string;
}

export async function getFilePreviewApi(
    space_id: string,
    file_id: string
): Promise<KnowledgeFilePreview> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const res = await request.get<any>(`/api/v1/knowledge/space/${space_id}/files/${file_id}/preview`);
    const data = res?.data ?? res;
    return {
        original_url: data?.original_url ?? "",
        preview_url: data?.preview_url ?? "",
        file_source: data?.file_source ?? "",
        source_url: data?.source_url ?? "",
        final_url: data?.final_url ?? "",
        web_title: data?.web_title ?? "",
        media_kind: data?.media_kind ?? "",
        html_preview_url: data?.html_preview_url ?? "",
    };
}

/**
 * Get file download URL. This is intentionally separate from preview because
 * viewing a file does not imply download permission.
 */
export async function getFileDownloadApi(
    space_id: string,
    file_id: string
): Promise<{ original_url: string; preview_url: string }> {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const res = await request.get<any>(`/api/v1/knowledge/space/${space_id}/files/${file_id}/download`);
    const data = res?.data ?? res;
    return {
        original_url: data?.original_url ?? "",
        preview_url: data?.preview_url ?? "",
    };
}

/**
 * Update a file's encoding (shougang feature). Owner/admin only.
 */
export async function updateFileEncoding(
    spaceId: string,
    fileId: string,
    encoding: string,
): Promise<KnowledgeFile> {
    return await request.put(
        `/api/v1/knowledge/space/${spaceId}/files/${fileId}/encoding`,
        { encoding },
    );
}

// ─────────────────────────────────────────────────────────────
// Version management (2.6 beta2)
// ─────────────────────────────────────────────────────────────

/** Single entry in a file's version history list */
export interface FileVersionEntry {
    version_id: number;
    version_no: number;
    is_primary: boolean;
    knowledge_file_id: number;
    original_file_name: string;
    file_code?: string | null;
    uploader_name?: string | null;
    uploader_id?: number | null;
    upload_time?: string | null;     // ISO datetime
    status?: number | null;          // mirrors FileStatus numeric values
}

/** Wrapping response from the versions endpoint */
export interface VersionListResponse {
    document_id: number;
    knowledge_id: number;
    title: string;
    doc_code?: string | null;
    current_primary_version_no?: number | null;
    versions: FileVersionEntry[];
}

/**
 * List all versions of a document (identified by any member knowledge_file_id).
 * GET /api/v1/knowledge/space/file/{knowledge_file_id}/versions
 */
export async function getFileVersionsApi(
    knowledge_file_id: number
): Promise<VersionListResponse> {
    const res = await request.get(
        `/api/v1/knowledge/space/file/${knowledge_file_id}/versions`
    ) as ApiResponse<VersionListResponse>;
    return res.data;
}

/** Payload for linking an existing file to a document as a new version */
export interface LinkAsNewVersionPayload {
    knowledge_file_id: number;
    target_document_id: number;
}

/** Response from linking a file as a new document version */
export interface LinkAsNewVersionResponse {
    document_id: number;
    new_version_no: number;
}

/**
 * Link an existing standalone file to a document as a new version.
 * POST /api/v1/knowledge/space/document/link
 *
 * `skip403Redirect` opts out of the global 403 redirect AND routes any non-200
 * business code through the unified interceptor pipeline — it translates
 * api_errors.<code>, toasts it, and rejects the promise so onError fires.
 */
export async function linkAsNewVersionApi(
    payload: LinkAsNewVersionPayload
): Promise<LinkAsNewVersionResponse> {
    const res = await request.post(
        `/api/v1/knowledge/space/document/link`,
        payload,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { skip403Redirect: true } as any,
    ) as ApiResponse<LinkAsNewVersionResponse>;
    return res.data;
}

/** Response from setting a version as primary */
export interface SetPrimaryResponse {
    document_id: number;
    new_primary_version_no: number;
}

/**
 * Promote a version to primary (the version that represents the document in search / display).
 * POST /api/v1/knowledge/space/version/{version_id}/set-primary
 */
export async function setPrimaryVersionApi(version_id: number): Promise<SetPrimaryResponse> {
    const res = await request.post(
        `/api/v1/knowledge/space/version/${version_id}/set-primary`,
        undefined,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { skip403Redirect: true } as any,
    ) as ApiResponse<SetPrimaryResponse>;
    return res.data;
}

/**
 * Delete a non-primary version (history record only; does not affect the document).
 * DELETE /api/v1/knowledge/space/version/{version_id}
 */
export async function deleteFileVersionApi(version_id: number): Promise<void> {
    await request.delete(
        `/api/v1/knowledge/space/version/${version_id}`,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { skip403Redirect: true } as any,
    );
}

/** Document entry returned by the keyword-search endpoint used in the link dialog */
export interface SearchableDocumentEntry {
    document_id: number;
    title: string;
    doc_code?: string | null;
    current_primary_version_no: number;
    primary_uploader_name?: string | null;
    primary_upload_time?: string | null;
}

/**
 * Search documents within a space by keyword — used to find a target document when linking versions.
 * current_file_id excludes the source file's own document from the results.
 * GET /api/v1/knowledge/space/{space_id}/document/search?keyword=...&current_file_id=...
 */
export async function searchDocumentsApi(
    space_id: number,
    keyword: string,
    current_file_id: number
): Promise<SearchableDocumentEntry[]> {
    const res = await request.get<ApiResponse<SearchableDocumentEntry[]>>(
        `/api/v1/knowledge/space/${space_id}/document/search`,
        { params: { keyword, current_file_id } }
    );
    return extractList<SearchableDocumentEntry>((res as any)?.data ?? res);
}

/** Candidate document entry returned by the similarity recommendation API */
export interface SimilarCandidateEntry {
    target_document_id: number;
    title: string;
    doc_code?: string;
    current_primary_version_no: number;
    similarity: number;
    primary_uploader_name?: string;
    primary_upload_time?: string;
}

/**
 * Get similar document candidates for a newly uploaded file.
 * GET /api/v1/knowledge/space/file/{file_id}/similar
 */
export async function getSimilarCandidatesApi(file_id: number): Promise<SimilarCandidateEntry[]> {
    const res = await request.get<ApiResponse<SimilarCandidateEntry[]>>(
        `/api/v1/knowledge/space/file/${file_id}/similar`
    );
    return extractList<SimilarCandidateEntry>((res as any)?.data ?? res);
}

/** Entry in the pending-similar-files list for a space */
export interface PendingSimilarFileEntry {
    knowledge_file_id: number;
    file_name: string;
    file_code?: string | null;
    candidate_count: number;
    current_primary_version_no?: number | null;
    primary_uploader_name?: string | null;
}

/**
 * List files in a space that have been flagged as similar (pending user review).
 * GET /api/v1/knowledge/space/{space_id}/similar-pending
 */
export async function getPendingSimilarFilesApi(space_id: number): Promise<PendingSimilarFileEntry[]> {
    const res = await request.get<ApiResponse<PendingSimilarFileEntry[]>>(
        `/api/v1/knowledge/space/${space_id}/similar-pending`
    );
    return extractList<PendingSimilarFileEntry>((res as any)?.data ?? res);
}

// ─────────────────────────────────────────────────────────────
// Version management dialog — reverse-direction merge APIs.
// These mirror the similar/search/link triplet above but restrict candidates
// to single-version documents and absorb the picked document INTO the current
// file's chain (instead of moving the current file into the target chain).
// Used by RelateDocumentPanel (the per-file version management entry).
// ─────────────────────────────────────────────────────────────

/**
 * Top-N single-version similar candidates for the current file's version dialog.
 * GET /api/v1/knowledge/space/file/{file_id}/version-recommendations
 */
export async function getVersionRecommendationsApi(
    file_id: number,
): Promise<SimilarCandidateEntry[]> {
    const res = await request.get<ApiResponse<SimilarCandidateEntry[]>>(
        `/api/v1/knowledge/space/file/${file_id}/version-recommendations`
    );
    return extractList<SimilarCandidateEntry>((res as any)?.data ?? res);
}

/**
 * Search single-version documents (keyword) — version management merge picker.
 * GET /api/v1/knowledge/space/{space_id}/document/version-search?keyword=...&current_file_id=...
 */
export async function searchVersionSourcesApi(
    space_id: number,
    keyword: string,
    current_file_id: number,
): Promise<SearchableDocumentEntry[]> {
    const res = await request.get<ApiResponse<SearchableDocumentEntry[]>>(
        `/api/v1/knowledge/space/${space_id}/document/version-search`,
        { params: { keyword, current_file_id } }
    );
    return extractList<SearchableDocumentEntry>((res as any)?.data ?? res);
}

/** Payload for merging a source document into the current file's chain */
export interface MergeIntoCurrentPayload {
    current_knowledge_file_id: number;
    source_document_id: number;
}

/**
 * Merge a single-version source document into the current file's document chain
 * as its new primary version. Source document is deleted afterwards.
 * POST /api/v1/knowledge/space/version/merge
 */
export async function mergeIntoCurrentApi(
    payload: MergeIntoCurrentPayload,
): Promise<LinkAsNewVersionResponse> {
    const res = await request.post(
        `/api/v1/knowledge/space/version/merge`,
        payload,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { skip403Redirect: true } as any,
    ) as ApiResponse<LinkAsNewVersionResponse>;
    return res.data;
}

/**
 * Dismiss the similar-file flag for a file (user chose not to link it to any document).
 * POST /api/v1/knowledge/space/file/{file_id}/dismiss-similar
 */
export async function dismissSimilarApi(file_id: number): Promise<void> {
    await request.post(
        `/api/v1/knowledge/space/file/${file_id}/dismiss-similar`,
        undefined,
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        { skip403Redirect: true } as any,
    );
}
