// @ts-strict-ignore
import { decodeErrorEnvelope, isApiError, isErrorEnvelope, normalizeApiError, resolveErrorMessageTemplate } from '@bisheng/api-client';
import { notification } from '@bisheng/ui';

import axios from "axios";
import i18next from "i18next";
axios.defaults.withCredentials = true;
const customAxios = axios.create({
    baseURL: import.meta.env.BASE_URL
    // 配置
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

customAxios.interceptors.request.use(function (config) {
    const token = localStorage.getItem('ws_token');
    if (token && !/^\/bisheng/.test(config.url)) {
        config.headers['Authorization'] = `Bearer ${token}`;
    }
    return config;
}, function (error) {
    return Promise.reject(error);
});

// Only registered local copy is eligible for user-facing errors.
function decodeEnvelopeMessage(envelope: any) {
    const statusCode = envelope?.status_code
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
    const envelope = await decodeErrorEnvelope(original?.data, { httpFailure: original?.status >= 400 }) ?? original?.data;
    return normalizeRequestError(cause, {
        response: original,
        envelope,
        message: String(i18next.t('api_errors:fallback')),
    });
}

customAxios.interceptors.response.use(async function (response) {
    const binary = response.data instanceof Blob || response.data instanceof ArrayBuffer;
    const decoded = binary ? await decodeErrorEnvelope(response.data) : undefined;
    const envelope = decoded ?? response.data;
    if (!isErrorEnvelope(envelope)) return response.data;
    if (envelope.status_code === 200) {
        const url = response.config?.url || '';
        if (url.includes('/user/login') || url.includes('/user/info')) clearSessionKickAck();
        return binary ? response.data : envelope.data;
    }
    if (envelope.status_code === 11010) return envelope;
    const error = await responseError(envelope, response);
    if (response.config.silent) return Promise.reject(error);
    const statusCode = envelope.status_code;
    if (statusCode === 11001) {
        if (shouldToastLicenseExpired()) {
            notification.open({ type: 'error', title: String(i18next.t('prompt')), description: error.message });
        }
        error.presentation = 'global';
        return Promise.reject(error);
    }
    // The login page owns the password-reset interaction.
    if (statusCode === 10601) return Promise.reject(error);
    if ([403, 404].includes(statusCode) && response.config.url !== '/api/v1/user/info') {
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
}, async function (cause) {
    const error = await responseError(cause);
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
});

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
