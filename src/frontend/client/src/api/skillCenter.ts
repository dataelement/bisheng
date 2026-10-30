import request from './request';
import { SkillError, type CenterSkill, type PersonalSkill, type PlatformSkill } from '~/components/Skills/types';

interface ApiResponse<T> { status_code: number; data: T }

export async function getSkillScope(userId: string): Promise<string> {
  const response = await request.get<ApiResponse<{ leaf_tenant_id: number }>>('/api/v1/user/current-tenant');
  if (response.status_code !== 200 || !Number.isSafeInteger(response.data?.leaf_tenant_id)) {
    throw new SkillError('identity');
  }
  return JSON.stringify([response.data.leaf_tenant_id, String(userId)]);
}

interface SkillRecord {
  id: number; name: string; display_name: string; description: string; enabled: boolean;
  source: 'platform' | 'personal'; content_hash: string; updated_at: string;
  builtin_key?: string | null; instructions?: string; files?: string[];
}

export async function getCenterSkills(): Promise<CenterSkill[]> {
  const response = await request.get<ApiResponse<SkillRecord[]>>('/api/v1/dsh/skills');
  if (response.status_code !== 200 || !Array.isArray(response.data)) throw new SkillError('platform');
  return response.data.map(row => {
    const shared = { id: `${row.source}:${row.source === 'platform' ? row.name : row.id}`, resourceId: row.id,
      name: row.name, displayName: row.display_name, description: row.description, enabled: row.enabled };
    return row.source === 'platform' ? { ...shared, source: 'platform', builtinKey: row.builtin_key } : { ...shared, source: 'personal',
      scope: '', updatedAt: row.updated_at, revision: row.content_hash, instructions: row.instructions ?? '',
      files: row.files ?? [], fileName: `${row.display_name}.zip`, size: 0, file: new Blob() };
  });
}
export async function getAvailableCenterSkills(): Promise<PlatformSkill[]> {
  return (await getCenterSkills()).filter((row): row is PlatformSkill => row.source === 'platform');
}
export async function setSkillAvailability(skill: CenterSkill, enabled: boolean) {
  const response = await request.put(`/api/v1/dsh/skills/${skill.resourceId}/availability`, { enabled });
  if (response.status_code !== 200) throw new SkillError('storage');
}
export async function uploadPersonalSkill(file: Blob, fileName: string, target?: PersonalSkill, clientId: string = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')) {
  const form = new FormData(); form.append('file', file, fileName); form.append('client_id', clientId);
  const response = await request.postMultiPart(`/api/v1/dsh/skills/personal${target ? `/${target.resourceId}` : ''}`, form);
  if (response.status_code !== 200) throw new SkillError('storage');
  return response.data.id as number;
}
export async function deletePersonalSkill(skill: PersonalSkill) {
  const response = await request.delete<ApiResponse<unknown>>(`/api/v1/dsh/skills/personal/${skill.resourceId}`);
  if (response.status_code !== 200) throw new SkillError('storage');
}
export async function downloadPersonalSkill(skill: PersonalSkill): Promise<Blob> {
  const response = await request.getResponse<{ data: Blob }>(`/api/v1/dsh/skills/personal/${skill.resourceId}/bundle`, { responseType: 'blob' });
  return response.data;
}
