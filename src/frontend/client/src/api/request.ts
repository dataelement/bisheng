// @ts-strict-ignore
/* eslint-disable @typescript-eslint/no-explicit-any */
import { decodeErrorEnvelope, isApiError, isErrorEnvelope, normalizeApiError, resolveErrorMessageTemplate, type ErrorPresentation } from '@bisheng/api-client';
import axios, { AxiosError, AxiosRequestConfig } from 'axios';
import i18next from "i18next";
import { setTokenHeader } from '~/api/chat/headers-helpers';
import { redirectToLogin } from '~/utils/loginRedirect';
import * as endpoints from '~/api/chat/api-endpoints';
import type * as t from '~/types/chat/types';

// 报错的时候是否弹窗
type ErrorOptions = {
  showError?: boolean;
  /** When true, the interceptor will NOT auto-redirect on 403. The caller handles it. */
  skip403Redirect?: boolean;
  /** When true, a 500 on this call does not cover the app with the maintenance overlay. */
  skipMaintenance?: boolean;
};

const customAxios = axios.create({
  baseURL: import.meta.env.BASE_URL
  // 配置
});

async function _get<T>(url: string, options?: AxiosRequestConfig & ErrorOptions): Promise<T> {
  const response = await customAxios.get(url, { ...options });
  return response.data;
}

async function _getResponse<T>(url: string, options?: AxiosRequestConfig & ErrorOptions): Promise<T> {
  return await customAxios.get(url, { ...options });
}

async function _post(url: string, data?: any, config?: AxiosRequestConfig & ErrorOptions) {
  const response = await customAxios.post(url, config ? data : JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json' },
    ...config
  });
  return response.data;
}

async function _postResponse<T>(url: string, data?: any, config?: AxiosRequestConfig & ErrorOptions): Promise<T> {
  // Mirror of _getResponse: returns the full Axios response so callers can
  // read headers (e.g. Content-Disposition for file downloads).
  return await customAxios.post(url, config ? data : JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json' },
    ...config,
  }) as unknown as T;
}

async function _postMultiPart(url: string, formData: FormData, options?: AxiosRequestConfig & ErrorOptions) {
  const response = await customAxios.post(url, formData, {
    ...options,
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

async function _postTTS(url: string, formData: FormData, options?: AxiosRequestConfig & ErrorOptions) {
  const response = await customAxios.post(url, formData, {
    ...options,
    headers: { 'Content-Type': 'multipart/form-data' },
    responseType: 'arraybuffer',
  });
  return response.data;
}

async function _put(url: string, data?: any, options?: AxiosRequestConfig & ErrorOptions) {
  const response = await customAxios.put(url, JSON.stringify(data), {
    ...options,
    headers: { 'Content-Type': 'application/json' },
  });
  return response.data;
}

async function _delete<T>(url: string, options?: AxiosRequestConfig & ErrorOptions): Promise<T> {
  const response = await customAxios.delete(url, { ...options });
  return response.data;
}

async function _deleteWithOptions<T>(url: string, options?: AxiosRequestConfig & ErrorOptions): Promise<T> {
  const response = await customAxios.delete(url, { ...options });
  return response.data;
}

async function _patch<T = unknown>(url: string, data?: any, options?: AxiosRequestConfig & ErrorOptions): Promise<T> {
  const response = await customAxios.patch(url, JSON.stringify(data), {
    ...options,
    headers: { 'Content-Type': 'application/json' },
  });
  return response.data;
}

let isRefreshing = false;
let failedQueue: { resolve: (value?: any) => void; reject: (reason?: any) => void }[] = [];

const refreshToken = (retry?: boolean): Promise<t.TRefreshTokenResponse | undefined> =>
  _post(endpoints.refreshToken(retry));

const dispatchTokenUpdatedEvent = (token: string) => {
  setTokenHeader(token);
  window.dispatchEvent(new CustomEvent('tokenUpdated', { detail: token }));
};

const processQueue = (error: AxiosError | null, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

export const translateApiErrorMessage = (data: any) => {
  const statusCodeKey = data?.status_code != null ? `api_errors.${data.status_code}` : '';
  const statusMessage = typeof data?.status_message === 'string' ? data.status_message : '';
  const statusMessageKey = statusMessage ? `api_errors.${statusMessage}` : '';
  const message = statusCodeKey && i18next.exists(statusCodeKey) ? String(i18next.t(statusCodeKey))
    : statusMessageKey && i18next.exists(statusMessageKey) ? String(i18next.t(statusMessageKey))
    : '';
  const translatedFallback = i18next.t('api_errors.fallback', { defaultValue: 'Request failed. Please try again.' });
  const fallback = typeof translatedFallback === 'string' && translatedFallback.trim() && translatedFallback !== 'api_errors.fallback'
    ? translatedFallback : 'Request failed. Please try again.';
  return resolveErrorMessageTemplate(message || '', data?.data, fallback);
};

const SESSION_KICKED_CODE = 10604
const SESSION_KICK_ACK_KEY = "bs:session-kicked-ack"
let sessionKickInProgress = false
let sessionKickHandler: ((message: string) => void) | null = null

export function setSessionKickHandler(handler: ((message: string) => void) | null) {
  sessionKickHandler = handler
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

function clearSessionKickAck() {
  try {
    sessionStorage.removeItem(SESSION_KICK_ACK_KEY)
  } catch {
    /* storage disabled */
  }
}

function isSessionKickedEnvelope(envelope: unknown): boolean {
  return Boolean(
    envelope &&
    typeof envelope === "object" &&
    (envelope as { status_code?: number }).status_code === SESSION_KICKED_CODE
  )
}

function beginSessionKick(envelope: unknown): boolean {
  if (hasSessionKickAck()) {
    sessionKickInProgress = true
    return true
  }
  if (sessionKickInProgress) return true
  if (!sessionKickHandler) return false
  sessionKickInProgress = true
  sessionKickHandler(translateApiErrorMessage(envelope))
  return true
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

const responsePresentation = new WeakMap<object, ErrorPresentation>();

customAxios.interceptors.response.use(
  async (response) => {
    const envelope = await decodeErrorEnvelope(response.data) ?? response.data;
    const url = response.config?.url || ""
    if (
      response.status >= 200 &&
      response.status < 300 &&
      (envelope?.status_code === 200 || envelope?.status_code == null) &&
      (url.includes("/user/login") || url.includes("/user/info") || url.includes("/api/user/me"))
    ) {
      clearSessionKickAck()
    }

    // License expired (gateway degradation): always surface a clear toast and reject,
    // regardless of per-call error flags, so end users learn it's an authorization
    // issue rather than a transient glitch. See feature 037.
    if (envelope?.status_code === 11001) {
      responsePresentation.set(response, 'global');
      const message = translateApiErrorMessage(envelope);
      if (message && shouldToastLicenseExpired()) {
        window.showToast?.({ message, status: 'warning' });
      }
      const err: any = new Error(message || 'license expired (11001)');
      err.status_code = 11001;
      err.status_message = envelope.status_message;
      err.response = response;
      return Promise.reject(err);
    }

    if (isSessionKickedEnvelope(envelope) && beginSessionKick(envelope)) {
      responsePresentation.set(response, 'global');
      const err: any = new Error(translateApiErrorMessage(envelope));
      err.status_code = SESSION_KICKED_CODE;
      err.status_message = envelope.status_message;
      err.response = response;
      return Promise.reject(err);
    }

    // Backend service exception surfaced as HTTP 200 + business code 500:
    // gateways often wrap upstream 5xx into a 200 envelope, so mirror the
    // HTTP-500 branch below and raise the global maintenance overlay here too.
    // Return early — the overlay covers the screen, no toast needed underneath.
    if (envelope?.status_code === 500 && !response.config.skipMaintenance) {
      responsePresentation.set(response, 'global');
      window.dispatchEvent(new CustomEvent('bs:service-maintenance'));
      return response;
    }

    // Legacy 403 default: redirect to /c/new?error=11403 unless the caller
    // explicitly opts out via skip403Redirect.
    if (envelope?.status_code === 403 && !response.config.skip403Redirect) {
      responsePresentation.set(response, 'global');
      localStorage.setItem('ERROR_REQUEST_PATH', response.config.url || '')
      location.href = `${__APP_ENV__.BASE_URL}/c/new?error=11403`;
      return response
    }

    // Unified business-error pipeline for callers that opted out of the 403
    // redirect: translate the api_errors.<code> i18n key, toast it, and reject
    // the promise so the caller's onError / .catch fires. Old call sites that
    // rely on silent failure (no skip403Redirect) keep the previous behavior.
    if (
      response.config.skip403Redirect
      && isErrorEnvelope(envelope)
      && envelope.status_code !== 200
    ) {
      const message = translateApiErrorMessage(envelope);
      const display = message;
      if (display && response.config.showError !== false) {
        if (window.showToast) responsePresentation.set(response, 'toast');
        window.showToast?.({ message: display, status: 'warning' });
      }
      const err: any = new Error(display || `request failed (${envelope.status_code})`);
      err.status_code = envelope.status_code;
      err.status_message = envelope.status_message;
      err.response = response;
      return Promise.reject(err);
    }

    if (response.config.showError && isErrorEnvelope(envelope) && envelope.status_code !== 200) {
      if (window.showToast) responsePresentation.set(response, 'toast');
      window.showToast?.({ message: translateApiErrorMessage(envelope), status: 'warning' });
    }
    return response;
  },
  async (error) => {
    const originalRequest = error.config;
    if (!error.response) {
      return Promise.reject(error);
    }

    // Gateway/backend service exception → surface the global maintenance overlay.
    // Event name mirrors SERVICE_MAINTENANCE_EVENT in SystemMaintenanceOverlay.tsx.
    if (error.response.status === 500 && !originalRequest?.skipMaintenance) {
      responsePresentation.set(error.response, 'global');
      window.dispatchEvent(new CustomEvent('bs:service-maintenance'));
    }

    if (originalRequest.url?.includes('/api/auth/2fa') === true) {
      return Promise.reject(error);
    }
    if (originalRequest.url?.includes('/api/auth/logout') === true) {
      return Promise.reject(error);
    }

    if (error.response.status === 401) {
      if (sessionKickInProgress) {
        responsePresentation.set(error.response, 'global');
        return Promise.reject(error);
      }
      const envelope = await decodeErrorEnvelope(error.response.data, { httpFailure: true }) ?? error.response.data;
      if (isSessionKickedEnvelope(envelope) && beginSessionKick(envelope)) {
        responsePresentation.set(error.response, 'global');
        return Promise.reject(error);
      }
    }

    if (error.response.status === 401 && !originalRequest._retry) {
      console.warn('401 error, refreshing token');
      originalRequest._retry = true;

      // Standalone guest chat links (/chat/flow/:flowId, /chat/assistant/:flowId)
      // are passwordless — never redirect to the login page from here.
      // Auth variants (/chat/flow/auth/..., /chat/assistant/auth/...) are excluded.
      const isGuestStandaloneChat =
        /\/chat\/(flow|assistant)\/(?!auth\/)[^/]+\/?$/.test(location.pathname);
      if (isGuestStandaloneChat) {
        return Promise.reject(error);
      }

      // redirectToLogin drops the bs:auth-state sentinel (so the next
      // /api/user/me success counts as a fresh session), stores the full
      // return target, prefers the SSO url, and is idempotent across the burst
      // of parallel 401s a page load produces.
      //
      // Still gated on MODE: bouncing local dev to the platform origin on every
      // 401 makes debugging painful. Routes where a blank page is useless carry
      // their own unconditional guard instead (see routes/RequireLogin.tsx).
      if (import.meta.env.MODE === 'production') {
        responsePresentation.set(error.response, 'global');
        redirectToLogin();
      }
      // } else {
      //   if (location.pathname.indexOf('login') === -1) {
      //     // location.href = '/workspace/login';
      //   }
      // }
      // location.href = '/'

      // if (isRefreshing) {
      //   try {
      //     const token = await new Promise((resolve, reject) => {
      //       failedQueue.push({ resolve, reject });
      //     });
      //     // originalRequest.headers['Authorization'] = 'Bearer ' + token;
      //     return await customAxios(originalRequest);
      //   } catch (err) {
      //     return Promise.reject(err);
      //   }
      // }

      // isRefreshing = true;

      try {
        // const response = await refreshToken(
        //   // Handle edge case where we get a blank screen if the initial 401 error is from a refresh token request
        //   originalRequest.url?.includes('api/auth/refresh') === true ? true : false,
        // );

        // const token = response?.token ?? '';

        // if (token) {
        //   originalRequest.headers['Authorization'] = 'Bearer ' + token;
        //   dispatchTokenUpdatedEvent(token);
        //   processQueue(null, token);
        //   return await customAxios(originalRequest);
        // } else if (window.location.href.includes('share/')) {
        //   console.log(
        //     `Refresh token failed from shared link, attempting request to ${originalRequest.url}`,
        //   );
        // } else {
        //   window.location.href = '/login';
        // }
      } catch (err) {
        processQueue(err as AxiosError, null);
        return Promise.reject(err);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(error);
  },
);

/** Keep authentication and routing intact; localize only outgoing failures. */
function normalizeRequestError(cause: unknown, options: Parameters<typeof normalizeApiError>[1]) {
  const error = normalizeApiError(cause, options);
  error.message = translateApiErrorMessage(error);
  return normalizeApiError(error, {
    ...options,
    transportMessages: {
      network: i18next.exists('api_errors.network_error') ? String(i18next.t('api_errors.network_error')) : undefined,
      timeout: i18next.exists('api_errors.request_timeout') ? String(i18next.t('api_errors.request_timeout')) : undefined,
    },
  });
}

export function showApiError(cause: unknown) {
  const error = normalizeRequestError(cause, { message: translateApiErrorMessage(cause) });
  if (error.kind !== 'canceled' && error.presentation === 'none' && window.showToast) {
    window.showToast({ message: error.message, status: 'warning' });
    error.presentation = 'toast';
  }
  return error;
}

async function normalizeRequestFailure(cause, response?) {
  if (isApiError(cause)) return normalizeRequestError(cause, { message: cause.message });
  const original = response ?? cause?.response;
  const envelope = await decodeErrorEnvelope(original?.data, { httpFailure: original?.status >= 400 }) ?? original?.data;
  const error = normalizeRequestError(cause, {
    response: original,
    envelope,
    message: translateApiErrorMessage(envelope),
  });
  if (original && responsePresentation.has(original)) error.presentation = responsePresentation.get(original)!;
  return error;
}

// A second response stage changes only the failure carrier. Authentication,
// maintenance, token-refresh queues and their ordering remain in the first stage.
customAxios.interceptors.response.use(async response => {
  const envelope = await decodeErrorEnvelope(response.data) ?? response.data;
  if (!isErrorEnvelope(envelope) || envelope.status_code === 200) return response;
  return Promise.reject(await normalizeRequestFailure(envelope, response));
}, async cause => Promise.reject(await normalizeRequestFailure(cause)));

const paramsSerializer = (params) => {
  return Object.keys(params)
    .map(key => {
      const value = params[key];
      if (value === undefined) {
        return null; // 只返回非undefined的值
      }
      if (Array.isArray(value)) {
        return value.map(val => `${key}=${val}`).join('&');
      }
      return `${key}=${value}`;
    })
    .filter(item => item !== null) // 过滤掉值为null的项
    .join('&');
}

export default {
  get: _get,
  getResponse: _getResponse,
  post: _post,
  postResponse: _postResponse,
  postMultiPart: _postMultiPart,
  postTTS: _postTTS,
  put: _put,
  delete: _delete,
  deleteWithOptions: _deleteWithOptions,
  patch: _patch,
  refreshToken,
  dispatchTokenUpdatedEvent,
  paramsSerializer
};
