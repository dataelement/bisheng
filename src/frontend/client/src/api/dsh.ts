import request from './request';
import { parseDshLaunchBase } from '~/utils/dshLaunch';

type Envelope<T> = { status_code: number; data: T };
export type DshBrowserConfig = { enabled: boolean; management_enabled: boolean; download_url: string | null; launch_url: string };
export type DshSession = {
  session_id: string; device_label: string | null; client_version: string | null;
  state: string; created_at: string; last_seen_at: string | null; expires_at: string;
};
export type DshSessionPage = { items: DshSession[]; next_cursor: string | null; has_more: boolean };
export type DshUsage = {
  month: string; billing_timezone: string; source: 'live' | 'persisted' | 'unavailable';
  as_of: string | null; unknown_pending: number | null;
  models: { model_id: number; name: string; used: number | null; limit: number | null; remaining: number | null }[];
};
function unwrap<T>(result: Envelope<T>): T {
  if (result.status_code !== 200) throw new Error('DSH request failed');
  return result.data;
}
export async function getDshBrowserConfig(signal?: AbortSignal): Promise<DshBrowserConfig> {
  const config = unwrap(await request.get<Envelope<DshBrowserConfig>>('/api/v1/dsh/browser-config', { signal }));
  if (typeof config?.enabled !== 'boolean' || typeof config.management_enabled !== 'boolean') throw new Error('Invalid DSH configuration');
  if (config.download_url !== null) {
    const url = new URL(config.download_url);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) throw new Error('Invalid download URL');
  }
  return { ...config, launch_url: parseDshLaunchBase(config.launch_url) };
}
export async function getDshSessions(cursor?: string | null, signal?: AbortSignal): Promise<DshSessionPage> {
  return unwrap(await request.get<Envelope<DshSessionPage>>('/api/v1/dsh/me/sessions', { params: { cursor: cursor || undefined, limit: 20 }, signal }));
}
export async function getDshUsage(signal?: AbortSignal): Promise<DshUsage> {
  return unwrap(await request.get<Envelope<DshUsage>>('/api/v1/dsh/me/usage', { signal }));
}
export async function revokeDshSession(sessionId: string): Promise<void> {
  unwrap(await request.post(`/api/v1/dsh/me/sessions/${encodeURIComponent(sessionId)}/revoke`, {}));
}
