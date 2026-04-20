/* eslint-disable @typescript-eslint/no-explicit-any */
import axios, { AxiosError, AxiosRequestConfig } from 'axios';
import i18next from "i18next";
import { setTokenHeader } from '~/api/chat/headers-helpers';
import { getPlatformAdminPanelUrl } from '~/utils/platformAdminUrl';
import * as endpoints from '~/api/chat/api-endpoints';
import type * as t from '~/types/chat/types';

// 报错的时候是否弹窗
type ErrorOptions = {
  showError?: boolean;
  /** When true, the interceptor will NOT auto-redirect on 403. The caller handles it. */
  skip403Redirect?: boolean;
};

const customAxios = axios.create({
  baseURL: import.meta.env.BASE_URL
  // 配置
});

async function _get<T>(url: string, options?: AxiosRequestConfig & ErrorOptions): Promise<T> {
  const response = await customAxios.get(url, { ...options });
  return response.data;
}

async function _getResponse<T>(url: string, options?: AxiosRequestConfig): Promise<T> {
  return await customAxios.get(url, { ...options });
}

async function _post(url: string, data?: any, config?: AxiosRequestConfig) {
  const response = await customAxios.post(url, config ? data : JSON.stringify(data), {
    headers: { 'Content-Type': 'application/json' },
    ...config
  });
  return response.data;
}

async function _postMultiPart(url: string, formData: FormData, options?: AxiosRequestConfig) {
  const response = await customAxios.post(url, formData, {
    ...options,
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}

async function _postTTS(url: string, formData: FormData, options?: AxiosRequestConfig) {
  const response = await customAxios.post(url, formData, {
    ...options,
    headers: { 'Content-Type': 'multipart/form-data' },
    responseType: 'arraybuffer',
  });
  return response.data;
}

async function _put(url: string, data?: any, options?: AxiosRequestConfig) {
  const response = await customAxios.put(url, JSON.stringify(data), {
    ...options,
    headers: { 'Content-Type': 'application/json' },
  });
  return response.data;
}

async function _delete<T>(url: string, options?: AxiosRequestConfig): Promise<T> {
  const response = await customAxios.delete(url, { ...options });
  return response.data;
}

async function _deleteWithOptions<T>(url: string, options?: AxiosRequestConfig): Promise<T> {
  const response = await customAxios.delete(url, { ...options });
  return response.data;
}

async function _patch(url: string, data?: any, options?: AxiosRequestConfig) {
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

customAxios.interceptors.response.use(
  (response) => {
    if (response.data.status_code === 403) {
      // Allow business code to handle 403 when skip403Redirect is set
      if (!response.config.skip403Redirect) {
        localStorage.setItem('ERROR_REQUEST_PATH', response.config.url || '')
        location.href = `${__APP_ENV__.BASE_URL}/c/new?error=11403`;
      }
      return response
    }

    if (response.config.showError && response.data && response.data.status_code !== 200) {
      console.log('业务错误:>> ', response.config.url, response.data);
      window.showToast?.({ message: i18next.t(`api_errors.${response.data.status_code}`, response.data.data), status: 'error' });
    }
    return response;
  },
  async (error) => {
    const originalRequest = error.config;
    if (!error.response) {
      return Promise.reject(error);
    }

    if (originalRequest.url?.includes('/api/auth/2fa') === true) {
      return Promise.reject(error);
    }
    if (originalRequest.url?.includes('/api/auth/logout') === true) {
      return Promise.reject(error);
    }

    if (error.response.status === 401 && !originalRequest._retry) {
      console.warn('401 error, refreshing token');
      originalRequest._retry = true;

      const thirdPartyLoginUrl = localStorage.getItem('THIRD_PARTY_LOGIN_URL');
      if (thirdPartyLoginUrl) {
        window.location.href = thirdPartyLoginUrl;
        return Promise.reject(error);
      }

      if (import.meta.env.MODE === 'production') {
        localStorage.setItem('LOGIN_PATHNAME', location.pathname)
        location.href = getPlatformAdminPanelUrl()
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
