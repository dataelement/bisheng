export type FailureCategory = 'database' | 'network' | 'model_service' | 'sso' | 'object_storage';

export interface FailureInfo {
    version: 1;
    failure_id: string;
    category: FailureCategory;
    service?: string;
    service_name?: string;
    operation?: string;
    occurred_at: string;
    trace_id?: string;
}

const CATEGORIES: string[] = ['database', 'network', 'model_service', 'sso', 'object_storage'];
const FAILURE_FIELDS = ['version', 'failure_id', 'category', 'service', 'service_name', 'operation', 'occurred_at', 'trace_id'];
const REQUEST_NETWORK_FAILURES = new WeakMap<object, FailureInfo>();

function record(value: unknown): Record<string, unknown> | undefined {
    return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}

function validText(value: unknown, maxLength = 512): value is string {
    // eslint-disable-next-line no-control-regex -- Rejecting ASCII controls in untrusted failure metadata is intentional.
    return typeof value === 'string' && value.trim().length > 0 && value.length <= maxLength && !/[\u0000-\u001f\u007f]/.test(value);
}

/** Unknown versions or malformed public metadata must never interrupt state updates. */
export function parseFailureInfo(value: unknown): FailureInfo | undefined {
    const raw = record(value);
    if (!raw || raw.version !== 1 || !validText(raw.failure_id, 128)
        || typeof raw.category !== 'string' || !CATEGORIES.includes(raw.category)
        || !validText(raw.occurred_at, 64)
        || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(raw.occurred_at)
        || !Number.isFinite(Date.parse(raw.occurred_at))) return undefined;
    if (!/^[A-Za-z0-9_-]+$/.test(raw.failure_id)) return undefined;
    const clean: Record<string, unknown> = { version: 1, failure_id: raw.failure_id, category: raw.category, occurred_at: raw.occurred_at };
    for (const key of ['service', 'service_name', 'operation', 'trace_id']) {
        if (raw[key] == null) continue;
        if (!validText(raw[key])) return undefined;
        clean[key] = raw[key];
    }
    if (typeof clean.service === 'string' && !/^[a-z][a-z0-9_-]{0,63}$/.test(clean.service)) return undefined;
    if (typeof clean.trace_id === 'string' && !/^[A-Za-z0-9_-]{1,128}$/.test(clean.trace_id)) return undefined;
    if (typeof clean.service_name === 'string' && /https?:\/\/|(?:password|secret|api[_ -]?key|access[_ -]?token|authorization|cookie|bearer)\s*[:= ]/i.test(clean.service_name)) return undefined;
    return clean as unknown as FailureInfo;
}

export interface TaskFailureMetadata {
    error_code?: number;
    error_type?: string;
    detail?: string;
    /** support reference for a failure with no dependency failure_id (the task's log trace id) */
    reference_id?: string;
    execution_id?: string;
    attempt_id?: string;
    recovery_subject_id?: string;
    model_id?: string | number;
    rate_limit_state?: 'recovering' | 'busy' | 'normal';
    resume_mode?: string;
    failure_info?: FailureInfo;
}

export interface DailyFailureMetadata {
    errorType?: string;
    errorDetail?: string;
    referenceId?: string;
    failureInfo?: FailureInfo;
    executionId?: string;
    attemptId?: string;
    recoverySubjectId?: string;
    modelId?: string | number;
    rateLimitState?: 'recovering' | 'busy' | 'normal';
    resumeMode?: string;
}

/** Task-mode umbrella codes: 11090 (model service) and 11091 (platform). They
    say which side failed, not what to do, so the card keeps its per-type copy. */
const UMBRELLA_FAILURE_CODES = new Set([11090, 11091]);

/** Only a registered numeric translation can supply business failure copy. */
export function localizedBusinessFailure(code: number | undefined, localize: (key: string, values?: Record<string, unknown>) => string, data?: unknown): string | undefined {
    if (!Number.isInteger(code) || code === undefined || code < 10000 || code > 99999 || code === 18106) return undefined;
    if (UMBRELLA_FAILURE_CODES.has(code)) return undefined;
    const key = `api_errors.${code}`;
    const variables: Record<string, string | number> = {};
    for (const [name, value] of Object.entries(record(data) ?? {})) {
        if (['detail', 'exception', 'error', 'error_message', 'error_msg'].includes(name)) continue;
        if (typeof value === 'number' || (validText(value, 256) && !/https?:\/\/|(?:password|secret|token|authorization|api[_ -]?key)\s*[:=]/i.test(value))) variables[name] = value;
    }
    const translated = localize(key, variables);
    return translated !== key ? translated : undefined;
}

export function dailyFailureMetadata(value: unknown): DailyFailureMetadata {
    const raw = taskFailureMetadata(value);
    return {
        errorType: raw?.error_type,
        ...(raw?.detail ? { errorDetail: raw.detail } : {}),
        ...(raw?.reference_id ? { referenceId: raw.reference_id } : {}),
        failureInfo: raw?.failure_info,
        ...(raw?.execution_id ? { executionId: raw.execution_id } : {}),
        ...(raw?.attempt_id ? { attemptId: raw.attempt_id } : {}),
        ...(raw?.recovery_subject_id ? { recoverySubjectId: raw.recovery_subject_id } : {}),
        ...(raw?.model_id !== undefined ? { modelId: raw.model_id } : {}),
        ...(raw?.rate_limit_state ? { rateLimitState: raw.rate_limit_state } : {}),
        ...(raw?.resume_mode ? { resumeMode: raw.resume_mode } : {}),
    };
}

/** Shared projection for persisted, reconciled and live task failures. */
export function taskFailureMetadata(value: unknown): TaskFailureMetadata | undefined {
    const raw = record(value);
    if (!raw) return undefined;
    const result: TaskFailureMetadata = { failure_info: parseFailureInfo(raw.failure_info) };
    for (const key of ['error_type', 'detail', 'execution_id', 'attempt_id', 'recovery_subject_id', 'resume_mode'] as const) {
        if (typeof raw[key] === 'string') result[key] = raw[key];
    }
    if (typeof raw.reference_id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(raw.reference_id)) result.reference_id = raw.reference_id;
    if (typeof raw.error_code === 'number') result.error_code = raw.error_code;
    if (typeof raw.model_id === 'string' || typeof raw.model_id === 'number') result.model_id = raw.model_id;
    if (raw.rate_limit_state === 'recovering' || raw.rate_limit_state === 'busy' || raw.rate_limit_state === 'normal') result.rate_limit_state = raw.rate_limit_state;
    return result;
}

/** Device/transport evidence only; callers create this once per failed stream. */
export function createBrowserNetworkFailure(): FailureInfo {
    return {
        version: 1,
        failure_id: `browser_${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}_${Math.random().toString(36).slice(2)}`}`,
        category: 'network',
        service: 'transport',
        occurred_at: new Date().toISOString(),
    };
}

/** Request errors carry trusted metadata only when the server included it. */
export function requestFailureMetadata(error: unknown): TaskFailureMetadata | undefined {
    const raw = record(error);
    const response = record(raw?.response);
    const envelope = record(response?.data) ?? raw;
    const payload = record(envelope?.data) ?? envelope;
    const metadata = taskFailureMetadata(payload);
    if (typeof envelope?.status_code === 'number' && metadata) metadata.error_code = envelope.status_code;
    const transportFailure = !response && ['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT'].includes(String(raw?.code ?? ''));
    const offline = typeof navigator !== 'undefined' && navigator.onLine === false;
    if (!metadata?.failure_info && (transportFailure || offline)) {
        const info = raw ? REQUEST_NETWORK_FAILURES.get(raw) ?? createBrowserNetworkFailure() : createBrowserNetworkFailure();
        if (raw) REQUEST_NETWORK_FAILURES.set(raw, info);
        return { ...metadata, failure_info: info };
    }
    return metadata;
}

/** Compare rendered provenance independently from the step's other extension fields. */
export function failureMetadataEqual(a: unknown, b: unknown): boolean {
    const left = parseFailureInfo(a);
    const right = parseFailureInfo(b);
    return FAILURE_FIELDS.every((key) => left?.[key as keyof FailureInfo] === right?.[key as keyof FailureInfo]);
}
