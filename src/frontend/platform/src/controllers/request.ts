import { knowledgeProcessingConflictVariant } from '@bisheng/knowledge/processing-conflicts';
// @ts-strict-ignore
import { decodeErrorEnvelope, isApiError, isErrorEnvelope, normalizeApiError, resolveErrorMessageTemplate, hasIndependentScope } from '@bisheng/api-client';
import type { ErrorEnvelope } from '@bisheng/api-client';
import { notification } from '@bisheng/ui';

import axios from "axios";
import i18next from "i18next";
import { workflowReferenceErrorMessage } from './workflowReferenceErrors';
import { managementRequestScope,requiresManagementScope,guardManagementResponse,readManagementScope,pauseManagementScopeForRequest,acceptManagementScope } from './managementScope';

window.addEventListener('storage', event => {
    if (event.key === 'bs:management-scope' && event.oldValue !== event.newValue) window.location.reload();
});
window.addEventListener('bisheng:management-scope-changed', () => window.location.reload());
axios.defaults.withCredentials = true;
const customAxios = axios.create({
    baseURL: import.meta.env.BASE_URL
    // Shared base URL.
});
export const requestInterceptor: {
    remoteLoginFuc?: (msg: string) => void
} = {};

const SESSION_KICKED_CODE = 10604
const SESSION_KICK_ACK_KEY = "bs:session-kicked-ack"
let sessionKickInProgress = false

function isSessionKickedEnvelope(envelope: unknown): boolean {
    return Boolean(
        envelope &&
        typeof envelope === "object" &&
        (envelope as { status_code?: number }).status_code === SESSION_KICKED_CODE
    )
}

function hasSessionKickAck(): boolean {
    try {
        return sessionStorage.getItem(SESSION_KICK_ACK_KEY) === "1"
    } catch {
        return false
    }
}

export function markSessionKickAck() {
    try {
        sessionStorage.setItem(SESSION_KICK_ACK_KEY, "1")
    } catch {
        /* storage disabled */
    }
}

export function clearSessionKickAck() {
    try {
        sessionStorage.removeItem(SESSION_KICK_ACK_KEY)
    } catch {
        /* storage disabled */
    }
}

function beginSessionKick(envelope: unknown): boolean {
    if (hasSessionKickAck()) {
        sessionKickInProgress = true
        return true
    }
    if (sessionKickInProgress) return true
    const handler = requestInterceptor.remoteLoginFuc
    if (!handler) return false
    sessionKickInProgress = true
    handler(decodeEnvelopeMessage(envelope))
    return true
}

export async function bootstrapManagementRequestScope() {
    return readManagementScope(
        async () => await customAxios.post('/api/v1/admin/request-scope/bootstrap') as unknown as {scope_tenant_id: number; source?: string},
        async () => await customAxios.get('/api/v1/admin/request-scope') as unknown as {scope_tenant_id: number; source?: string},
    );
}

customAxios.interceptors.request.use(async function (config) {
    Object.assign(config.headers, requestAuthHeaders(config.url || ''));
    const scoped = config.managementContext !== 'independent' && !hasIndependentScope(config.headers) && requiresManagementScope(config.method || 'get', config.url || '', config.baseURL);
    if (scoped) await bootstrapManagementRequestScope();
    config.managementScopeSnapshot = scoped ? managementRequestScope() : null;
    if (scoped && config.managementScopeSnapshot !== null) {
        config.headers['X-Management-Tenant'] = String(config.managementScopeSnapshot);
    }
    return config;
}, function (error) {
    return Promise.reject(error);
});

// Only registered local copy is eligible for user-facing errors.
function rateLimitDiscoveryMessage(envelope: unknown): string {
    if (!isErrorEnvelope(envelope) || envelope.status_code !== 10812) return '';
    const data = envelope.data;
    const reason = data && typeof data === 'object' ? (data as { reason?: unknown }).reason : undefined;
    if (reason !== 'rate_limit') return '';
    const key = 'model:discoveryError_rate_limit';
    if (!i18next.exists(key)) return '';
    const message = i18next.t(key);
    return typeof message === 'string' && message && message !== key ? message : '';
}

// A processing conflict (10999) only says "a conflicting operation is processing
// this resource", which leaves the user with nothing to do. The backend names
// the real blocker in data.reason; map it to actionable copy from the knowledge
// namespace. An unmapped reason keeps the generic api_errors message, and an
// unloaded namespace falls back the same way (the knowledge page has already
// loaded it by the time one of these requests can run).
function knowledgeProcessingConflictMessage(envelope: unknown): string {
    const variant = knowledgeProcessingConflictVariant(envelope);
    if (!variant) return '';
    const key = `knowledge:f118.processing_conflict_${variant}`;
    if (!i18next.exists(key)) return '';
    const message = i18next.t(key);
    return typeof message === 'string' && message && message !== key ? message : '';
}

function decodeEnvelopeMessage(value: unknown) {
    const envelope = value && typeof value === 'object' ? value as Partial<ErrorEnvelope> : undefined;
    const statusCode = envelope?.status_code
    if (statusCode === 422 && Array.isArray(envelope.status_message)) {
        // Validation responses carry user-facing messages per field. Keep
        // input values, contexts and arbitrary server diagnostics out of copy.
        const messages = envelope.status_message.flatMap(issue => {
            if (!issue || typeof issue !== 'object' || typeof issue.msg !== 'string'
                || typeof issue.type !== 'string' || !Array.isArray(issue.loc)) return [];
            return issue.msg.trim() ? [issue.msg.trim()] : [];
        });
        if (messages.length) return [...new Set(messages)].join('\n');
    }
    const rateLimitMessage = rateLimitDiscoveryMessage(envelope);
    if (rateLimitMessage) return rateLimitMessage;
    const processingConflictMessage = knowledgeProcessingConflictMessage(envelope);
    if (processingConflictMessage) return processingConflictMessage;
    const workflowReferenceMessage = workflowReferenceErrorMessage(envelope);
    if (workflowReferenceMessage) return workflowReferenceMessage;
    const statusMessage = typeof envelope?.status_message === 'string' ? envelope.status_message : '';
    const codeKey = `api_errors:${statusCode}`;
    const i18Msg = i18next.exists(codeKey) ? i18next.t(codeKey) : '';

    const statusMessageKeyMap: Record<string, string> = {
        "person id is required": "api_errors:21013",
        "person id already exists": "api_errors:personIdAlreadyExists",
        "person id already belongs to a deleted account. please restore the original account.": "api_errors:21020",
        "department name already exists at this level": "api_errors:21001",
        "department not found": "api_errors:21000",
        "cannot delete department with children": "api_errors:21002",
        "cannot delete department with members": "api_errors:21003",
        "cannot move department to its own subtree": "api_errors:21004",
        "third-party synced department is read-only": "api_errors:21005",
        "root department already exists for this tenant": "api_errors:21006",
        "user is already a member of this department": "api_errors:21007",
        "user is not a member of this department": "api_errors:21008",
        "no permission for this department operation": "api_errors:21009",
        "password must be at least 8 characters and include upper, lower, digit and symbol": "api_errors:21010",
        "one or more roles are not assignable in this department": "api_errors:21011",
        "cannot delete user while data assets exist": "api_errors:21014",
        "only local accounts may be deleted from organization management": "api_errors:21015",
        "only archived departments can be permanently deleted": "api_errors:21016",
        "archived departments cannot be modified": "api_errors:21017",
        "cannot restore department while parent department is archived": "api_errors:21018",
    }

    const normalizedStatusMessage = statusMessage.trim().toLowerCase()
    const mappedStatusMessageKey = Object.hasOwn(statusMessageKeyMap, normalizedStatusMessage) ? statusMessageKeyMap[normalizedStatusMessage] : undefined
    const i18MsgFromStatus = mappedStatusMessageKey
        ? i18next.t(mappedStatusMessageKey)
        : null

    const finalMsg = i18MsgFromStatus && i18MsgFromStatus !== mappedStatusMessageKey
        ? i18MsgFromStatus
        : i18Msg

    const translatedFallback = i18next.t('api_errors:fallback', { defaultValue: 'Request failed. Please try again.' });
    const fallback = typeof translatedFallback === 'string' && translatedFallback.trim() && translatedFallback !== 'api_errors:fallback'
        ? translatedFallback : 'Request failed. Please try again.';
    return resolveErrorMessageTemplate(String(finalMsg || ''), envelope?.data,
        fallback);
}

// License degradation (gateway returns 11001): throttle the toast so a burst of
// failing business calls doesn't flood the user with duplicate notices.
let lastLicenseExpiredToastAt = 0;
function shouldToastLicenseExpired(): boolean {
    const now = Date.now();
    if (now - lastLicenseExpiredToastAt > 5000) {
        lastLicenseExpiredToastAt = now;
        return true;
    }
    return false;
}

function normalizeRequestError(cause: unknown, options: Parameters<typeof normalizeApiError>[1]) {
    const error = normalizeApiError(cause, options);
    error.message = decodeEnvelopeMessage(error);
    return normalizeApiError(error, {
        ...options,
        transportMessages: {
            network: i18next.exists('api_errors:network_error') ? String(i18next.t('api_errors:network_error')) : undefined,
            timeout: i18next.exists('api_errors:request_timeout') ? String(i18next.t('api_errors:request_timeout')) : undefined,
        },
    });
}

export function showApiError(cause: unknown) {
    const error = normalizeRequestError(cause, { message: String(i18next.t('api_errors:fallback')) });
    if (error.kind !== 'canceled' && error.presentation === 'none') {
        notification.open({ type: 'error', title: String(i18next.t('prompt')), description: error.message });
        error.presentation = 'toast';
    }
    return error;
}

async function responseError(cause, response?) {
    if (isApiError(cause)) return normalizeRequestError(cause, { message: cause.message });
    const original = response ?? cause?.response;
    const envelope = isErrorEnvelope(cause) ? cause
        : await decodeErrorEnvelope(original?.data, { httpFailure: original?.status >= 400 }) ?? original?.data;
    return normalizeRequestError(cause, {
        response: original,
        envelope,
        message: String(i18next.t('api_errors:fallback')),
    });
}

export async function handleRequestResponse(response) {
    try {
        if (response.config?.managementScopeSnapshot != null)
            guardManagementResponse(response.headers,response.config?.managementScopeSnapshot);
    } catch {
        return Promise.reject(await responseError({status_code:19704,status_message:'management_scope_changed'},response));
    }
    const binary = response.data instanceof Blob || response.data instanceof ArrayBuffer;
    const decoded = binary ? await decodeErrorEnvelope(response.data) : undefined;
    const envelope = decoded ?? response.data;
    if (!isErrorEnvelope(envelope)) return response.data;
    if (envelope.status_code === 200) {
        if ((response.config?.url || '').includes('/user/login')) acceptManagementScope(null);
        const url = response.config?.url || '';
        if (url.includes('/user/login') || url.includes('/user/info')) clearSessionKickAck();
        return binary ? response.data : envelope.data;
    }
    if (envelope.status_code === 11010) return envelope;
    const error = await responseError(envelope, response);
    const statusCode = envelope.status_code;
    if ([19703, 19704, 19705].includes(statusCode)) pauseManagementScopeForRequest(response.config);
    if (response.config.silent) return Promise.reject(error);
    if (statusCode === 11001) {
        if (shouldToastLicenseExpired()) {
            notification.open({ type: 'error', title: String(i18next.t('prompt')), description: error.message });
        }
        error.presentation = 'global';
        return Promise.reject(error);
    }
    // The login page owns the password-reset interaction.
    if (statusCode === 10601) return Promise.reject(error);
    // Missing auxiliary resources belong to their callers; they must not
    // replace the current page. Route-level 404 handling remains in the router.
    if (statusCode === 403 && response.config.url !== '/api/v1/user/info') {
        localStorage.setItem('noAccessUrl', response.request?.responseURL ?? response.config.url ?? '');
        if (response.config.method === 'get') {
            location.href = __APP_ENV__.BASE_URL + '/' + statusCode;
            error.presentation = 'global';
        } else if (response.config.showError !== false) showApiError(error);
        return Promise.reject(error);
    }
    if ([10599, 17005].includes(statusCode)) {
        location.href = `${__APP_ENV__.BASE_URL}/build/apps?error=${statusCode}`;
        error.presentation = 'global';
        return Promise.reject(error);
    }
    if (isSessionKickedEnvelope(envelope) && beginSessionKick(envelope)) {
        error.presentation = 'global';
        return Promise.reject(error);
    }
    if (response.config.showError !== false) showApiError(error);
    return Promise.reject(error);
}

export async function handleRequestError(cause) {
    const error = await responseError(cause);
    if ([19703, 19704, 19705].includes(error.status_code)) pauseManagementScopeForRequest(cause?.config ?? cause?.response?.config);
    if (error.httpStatus === 401) {
        error.presentation = 'global';
        if (sessionKickInProgress) return Promise.reject(error);
        if (isSessionKickedEnvelope(error) && beginSessionKick(error)) return Promise.reject(error);
        const hadSession = !!localStorage.getItem('ws_token') || !!localStorage.getItem('UUR_INFO');
        localStorage.removeItem('ws_token');
        const thirdPartyLoginUrl = localStorage.getItem('THIRD_PARTY_LOGIN_URL');
        localStorage.removeItem('UUR_INFO');
        if (thirdPartyLoginUrl) {
            window.location.href = thirdPartyLoginUrl;
            return Promise.reject(error);
        }
        if (hadSession) {
            const base = (__APP_ENV__.BASE_URL || '').replace(/\/$/, '');
            window.location.href = `${base}/`;
        }
        return Promise.reject(error);
    }
    if (!cause.config?.silent && cause.config?.showError !== false) showApiError(error);
    return Promise.reject(error);
}

customAxios.interceptors.response.use(handleRequestResponse, handleRequestError);

export default customAxios;

/** @deprecated Call the request directly and handle its rejection at the owning UI boundary. */
export function captureAndAlertRequestErrorHoc<T>(apiFunc: Promise<T>): Promise<T> {
    return apiFunc.catch(cause => {
        throw showApiError(cause);
    });
}

/** Consume rejections only at a UI event boundary; inner request chains still reject. */
export function handleUiRequest<Args extends unknown[]>(handler: (...args: Args) => unknown) {
    return (...args: Args): void => {
        void Promise.resolve().then(() => handler(...args)).catch(showApiError);
    };
}

export function requestAuthHeaders(url: string): Record<string, string> {
    const token = localStorage.getItem("ws_token");
    return token && !/^\/bisheng/.test(url) ? { Authorization: `Bearer ${token}` } : {};
}
