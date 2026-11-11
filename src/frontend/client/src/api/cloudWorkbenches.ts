import request from './request';

export interface CloudWorkbench {
  id: string;
  name: string;
  description: string;
  entry_url: string;
}

export interface CloudWorkbenchPage {
  items: CloudWorkbench[];
  next_cursor: string | null;
}

export async function getCloudWorkbenches(cursor?: string | null, signal?: AbortSignal): Promise<CloudWorkbenchPage> {
  const response = await request.get<{ status_code: number; data: CloudWorkbenchPage }>('/api/v1/apps/workbenches', { params: cursor ? { cursor } : {}, signal });
  if (response.status_code !== 200 || !Array.isArray(response.data?.items)) throw new Error('Cloud workbench catalog unavailable');
  return response.data;
}
