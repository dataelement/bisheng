export type ApiErrorKind = 'business' | 'http' | 'network' | 'timeout' | 'canceled' | 'invalid-response';
export type ErrorPresentation = 'none' | 'toast' | 'inline' | 'global';

export interface ApiErrorResponse {
  status: number;
  data: unknown;
}

export interface ErrorEnvelope {
  status_code: number;
  status_message?: unknown;
  data?: unknown;
}

interface NormalizeOptions {
  message: string;
  response?: ApiErrorResponse;
  envelope?: unknown;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' ? value as Record<string, unknown> : {};
}

export function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  return typeof record(value).status_code === 'number' && Number.isFinite(record(value).status_code);
}

export class ApiError extends Error {
  readonly kind: ApiErrorKind;
  readonly httpStatus?: number;
  readonly status_code?: number;
  readonly status_message?: unknown;
  readonly data?: unknown;
  readonly response?: ApiErrorResponse;
  readonly code?: string;
  readonly cause: unknown;
  presentation: ErrorPresentation = 'none';

  constructor(cause: unknown, options: NormalizeOptions) {
    super(options.message);
    this.name = 'ApiError';
    this.cause = cause;
    const original = record(cause);
    const candidate = options.response ?? original.response;
    const response = typeof record(candidate).status === 'number' ? candidate as ApiErrorResponse : undefined;
    this.response = response;
    this.httpStatus = response?.status;
    const envelope = [options.envelope, response?.data, cause].find(isErrorEnvelope);
    this.status_code = envelope?.status_code;
    this.status_message = envelope?.status_message;
    this.data = envelope?.data;
    this.code = typeof original.code === 'string' ? original.code : undefined;
    this.kind = this.code === 'ERR_CANCELED' ? 'canceled'
      : this.code === 'ECONNABORTED' || this.code === 'ETIMEDOUT' ? 'timeout'
      : response && (response.status < 200 || response.status >= 300) ? 'http'
      : envelope ? 'business'
      : this.code || original.isAxiosError ? 'network' : 'invalid-response';
  }
}

export function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

export function normalizeApiError(cause: unknown, options: NormalizeOptions): ApiError {
  return isApiError(cause) ? cause : new ApiError(cause, options);
}

export function shouldRetryApiError(error: unknown): boolean {
  return !isApiError(error) || (error.presentation !== 'global'
    && error.kind !== 'business' && error.kind !== 'canceled' && error.kind !== 'invalid-response');
}

/** Decode separately: never replace the transport response or its binary body. */
export async function decodeErrorEnvelope(value: unknown, options: { httpFailure?: boolean } = {}): Promise<ErrorEnvelope | undefined> {
  if (isErrorEnvelope(value)) return value;
  try {
    let source: string;
    if (typeof Blob !== 'undefined' && value instanceof Blob) {
      if (!options.httpFailure && !value.type.toLowerCase().includes('json')) return undefined;
      source = typeof value.text === 'function' ? await value.text() : await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsText(value);
      });
    } else if (value instanceof ArrayBuffer || ArrayBuffer.isView(value)) {
      source = new TextDecoder().decode(value as ArrayBuffer);
    } else {
      return undefined;
    }
    const parsed: unknown = JSON.parse(source);
    return isErrorEnvelope(parsed) ? parsed : undefined;
  } catch {
    return undefined;
  }
}

/** Format backend parameters without leaking an unresolved server template. */
export function resolveErrorMessageTemplate(message: string, data: unknown, fallback: string): string {
  const values = record(data);
  const rendered = message.replace(/\{\{?(\w+)\}?\}/g, (placeholder, key: string) => {
    const value = values[key];
    return typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean' ? String(value) : placeholder;
  });
  return rendered.trim() && !/\{\{?\w+\}?\}/.test(rendered) && !/^api_errors[.:]/.test(rendered)
    ? rendered : fallback;
}
