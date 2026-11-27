/** Browser metadata contains no Access or Refresh credential. */
export interface AuthSessionMetadata {
  session_id: string;
  access_expires_at: string;
  refresh_expires_at: string | null;
  session_expires_at: string;
  refresh_mode: 'cookie' | 'native' | 'host';
  delivery_state: 'PENDING_WEB_BIND' | 'BOUND';
  csrf_token?: string;
  default_entry?: string;
  auth_source?: 'platform' | 'legacy_dsh';
  /** Physical cookie retention from the session's frozen server policy. */
  cookie_retention_seconds?: number;
}
export interface AuthResponse { status: number; data: unknown }
export type AuthTransport = (method: 'GET' | 'POST', path: string,
  body?: unknown, headers?: Record<string, string>) => Promise<AuthResponse>;
export interface AuthEnvironment {
  selectSession(session: string | null, cookieRetentionSeconds?: number): void;
  selectedSession(): string | null;
  clearLegacyAuth(): void;
  publish(event: AuthEvent): void;
  subscribe(listener: (event: AuthEvent) => void): () => void;
  lock<T>(callback: (isCurrent: () => boolean) => Promise<T>): Promise<T>;
  now(): number;
  hostOwned?(): boolean;
  requestHostRenewal?(): void;
}
export interface AuthEvent { type: 'login' | 'logout' | 'refresh'; session: string | null }
export interface PlatformLoginInput {
  user_name: string;
  password: string;
  captcha_key?: string;
  captcha?: string;
}
export class AuthSessionError extends Error {
  get status_code(): number { return this.code; }
  get data(): { auth_reason: string; retryable: boolean } { return { auth_reason: this.reason, retryable: this.retryable }; }
  get httpStatus(): number { return this.status; }
  constructor(public readonly status: number, public readonly code: number,
    public readonly reason: string, public readonly retryable: boolean) {
    super(reason);
    this.name = 'AuthSessionError';
  }
}
