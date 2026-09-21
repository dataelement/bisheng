import request from './request';
import { parseDshLaunchBase } from '~/utils/dshLaunch';

type Envelope<T> = { status_code: number; data: T };
export type DshBrowserConfig = { enabled: boolean; management_enabled: boolean; download_url: string | null; launch_url: string };
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
export type DshUsageMetrics = {
    message_count: number
    qa_count: number
    failed_count: number
    cancelled_count: number
    running_count: number
    usage_unknown_count: number
    recorded_usage_count: number
    missing_usage_count: number
    input_tokens: number | null
    output_tokens: number | null
    total_tokens: number | null
}

export type DshUsageTimeBucket = DshUsageMetrics & {
    start_at: string
    end_at: string
}

export type DshUsageTimeSummary = {
    start_at: string
    end_at: string
    timezone: 'Asia/Shanghai'
    granularity: 'hour' | 'day'
    totals: DshUsageMetrics
    points: DshUsageTimeBucket[]
}

export async function getDshUsageSummary(signal?: AbortSignal): Promise<DshUsageTimeSummary> {
  return unwrap(await request.get<Envelope<DshUsageTimeSummary>>('/api/v1/dsh/me/usage-summary', { signal }));
}
