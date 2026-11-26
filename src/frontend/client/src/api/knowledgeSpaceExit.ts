import request, { prepareBrowserHeaders } from './request';

export type SpaceExitStatus = {
  can_exit: boolean;
  reason: 'creator' | 'organization_grant' | 'no_personal_grant' | null;
};

export async function resolveSpaceExitScope(): Promise<string> {
  const headers = await prepareBrowserHeaders('GET', '/api/v1/knowledge/space/1/exit-status');
  const tenant = headers['X-Management-Tenant'];
  if (!tenant) throw new Error('Knowledge space exit requires a confirmed tenant scope');
  return tenant;
}

export async function getSpaceExitStatus(spaceId: string): Promise<SpaceExitStatus> {
  const { data } = await request.get<{ data: SpaceExitStatus }>(
    `/api/v1/knowledge/space/${encodeURIComponent(spaceId)}/exit-status`,
  );
  return data;
}
