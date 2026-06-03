/**
 * F028 — Workstation conversation export & import-to-knowledge API client.
 *
 * Three calls back the corresponding backend endpoints under
 *   /api/v1/chat/messages/{export,import-to-knowledge}
 *   /api/v1/knowledge/space/uploadable
 *
 * Naming convention: function args are camelCase (frontend style); the
 * request body keys are mapped to the snake_case the backend DTO expects.
 */

import type { AxiosResponse } from 'axios';
import request from './request';

// Standard backend envelope used by the JSON endpoints
interface ApiResponse<T> {
    status_code: number;
    status_message: string;
    data: T;
}

export type ExportFormat = 'docx' | 'pdf' | 'md' | 'txt';

interface ExportMessagesPayload {
    chatId: string;
    messageIds: number[];
    format: ExportFormat;
}

export interface ExportedFile {
    blob: Blob;
    /** Filename decoded from the server's Content-Disposition header. */
    filename: string;
    mimeType: string;
}

interface ImportMessagesPayload {
    chatId: string;
    messageIds: number[];
    knowledgeSpaceId: number;
    parentId: number | null;
}

export interface ImportMessagesResult {
    file_id: number;
    target_filename: string;
    dup_renamed: boolean;
}

interface UploadableSpaceRow {
    id: number;
    name: string;
    icon: string | null;
    description: string | null;
}

/** Minimal shape consumed by AddToKnowledgeModal's space picker. */
export interface UploadableSpace {
    id: string;
    name: string;
    description?: string;
    icon?: string;
}

// ─── Export ────────────────────────────────────────────────────────────────

/**
 * Export selected messages as Word / PDF / Markdown / TXT.
 *
 * Returns the binary payload together with the filename the backend chose
 * (preferred over re-deriving on the client to keep the rule in one place).
 */
export async function exportMessagesApi(payload: ExportMessagesPayload): Promise<ExportedFile> {
    const body = {
        chat_id: payload.chatId,
        message_ids: payload.messageIds,
        format: payload.format,
    };
    const res = await request.postResponse<AxiosResponse<Blob>>(
        '/api/v1/chat/messages/export',
        body,
        { responseType: 'blob' },
    );
    // On a business error the backend returns a JSON envelope (HTTP 200), but
    // we requested a blob, so the shared interceptor can't read status_code and
    // resolves. Without this guard the error JSON would be "downloaded" as the
    // exported file instead of surfacing the 12064 "文件生成失败" prompt.
    const blob = res.data;
    if (blob && typeof blob.type === 'string' && blob.type.includes('application/json')) {
        let envelope: { status_code?: number; status_message?: string } = {};
        try {
            envelope = JSON.parse(await blob.text());
        } catch {
            // not parseable — fall through and treat as a generic failure
        }
        if (!envelope.status_code || envelope.status_code !== 200) {
            const err = new Error(
                envelope.status_message || 'export failed',
            ) as Error & { status_code?: number; status_message?: string };
            err.status_code = envelope.status_code;
            err.status_message = envelope.status_message;
            throw err;
        }
    }
    const filename = parseContentDispositionFilename(
        (res.headers?.['content-disposition'] as string) ?? '',
    );
    return {
        blob: res.data,
        filename: filename ?? `export.${payload.format}`,
        mimeType: (res.headers?.['content-type'] as string) ?? 'application/octet-stream',
    };
}

// ─── Import to knowledge space ─────────────────────────────────────────────

export async function importMessagesToKnowledgeApi(
    payload: ImportMessagesPayload,
): Promise<ImportMessagesResult> {
    const body = {
        chat_id: payload.chatId,
        message_ids: payload.messageIds,
        knowledge_space_id: payload.knowledgeSpaceId,
        parent_id: payload.parentId,
    };
    // request.post's _post is non-generic and returns axios response.data
    // (typed as any). Cast to the expected envelope shape locally.
    const res = (await request.post(
        '/api/v1/chat/messages/import-to-knowledge',
        body,
    )) as ApiResponse<ImportMessagesResult>;
    // The shared interceptor resolves (does NOT reject) on business errors when
    // the request opts out of both skip403Redirect and showError, so guard here:
    // surface 12065/12066/12067/12068… as a thrown error carrying the backend
    // message, otherwise the caller's try-block would falsely toast "success".
    if (res.status_code !== 200) {
        const err = new Error(
            res.status_message || `import failed (${res.status_code})`,
        ) as Error & { status_code?: number; status_message?: string };
        err.status_code = res.status_code;
        err.status_message = res.status_message;
        throw err;
    }
    return res.data;
}

// ─── Uploadable knowledge spaces (F028 picker data source) ─────────────────

/**
 * List knowledge spaces the current user can upload files into (upload_file
 * permission). Used by AddToKnowledgeModal in the workstation export flow
 * — not by the article / channel-sync flows.
 */
export async function listUploadableSpacesApi(keyword?: string): Promise<UploadableSpace[]> {
    const res = await request.get<ApiResponse<{ data: UploadableSpaceRow[] }>>(
        '/api/v1/knowledge/space/uploadable',
        { params: keyword ? { keyword } : undefined },
    );
    return res.data.data.map((row) => ({
        id: String(row.id),
        name: row.name,
        description: row.description ?? undefined,
        icon: row.icon ?? undefined,
    }));
}

// ─── Helpers ───────────────────────────────────────────────────────────────

/**
 * Pull the filename out of a Content-Disposition header.
 *
 * Prefers the RFC 5987 ``filename*=UTF-8''<percent-encoded>`` form (so
 * Chinese filenames round-trip correctly) and falls back to the legacy
 * ``filename="..."`` parameter for old clients/proxies that strip the *
 * form. Returns null when neither is parseable.
 */
export function parseContentDispositionFilename(header: string): string | null {
    if (!header) return null;
    const star = /filename\*\s*=\s*([^']*)''([^;]+)/i.exec(header);
    if (star) {
        try {
            return decodeURIComponent(star[2].trim());
        } catch {
            // fall through to ASCII fallback
        }
    }
    const ascii = /filename\s*=\s*"?([^";]+)"?/i.exec(header);
    return ascii ? ascii[1].trim() : null;
}

/**
 * Trigger a browser download for an already-fetched ExportedFile.
 * Caller pattern: ``exportMessagesApi(...).then(triggerBrowserDownload)``.
 */
export function triggerBrowserDownload(file: ExportedFile): void {
    const url = window.URL.createObjectURL(file.blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = file.filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    window.URL.revokeObjectURL(url);
}
