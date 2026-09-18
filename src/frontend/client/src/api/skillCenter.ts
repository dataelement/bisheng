import request from './request';
import { SkillError, type PlatformSkill } from '~/components/Skills/types';

interface ApiResponse<T> { status_code: number; data: T }
interface SelectableSkill { name: string; display_name: string; description: string }

export async function getSkillScope(userId: string): Promise<string> {
  const response = await request.get<ApiResponse<{ leaf_tenant_id: number }>>('/api/v1/user/current-tenant');
  if (response.status_code !== 200 || !Number.isSafeInteger(response.data?.leaf_tenant_id)) {
    throw new SkillError('identity');
  }
  return JSON.stringify([response.data.leaf_tenant_id, String(userId)]);
}

export async function getAvailableCenterSkills(): Promise<PlatformSkill[]> {
  const response = await request.get<ApiResponse<SelectableSkill[]>>('/api/v1/linsight/skill/selectable');
  if (response.status_code !== 200 || !Array.isArray(response.data)) throw new SkillError('platform');
  return response.data.map((skill) => ({
    id: `platform:${skill.name}`,
    name: skill.name,
    displayName: skill.display_name || skill.name,
    description: skill.description,
    enabled: true,
    source: 'platform',
  }));
}
