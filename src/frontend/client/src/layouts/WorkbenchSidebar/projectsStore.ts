import { useMemo } from 'react';
import { useChatProjects } from '~/hooks/useChatProjects';

export const PROJECT_NAME_MAX_LENGTH = 30;
const LEGACY_PROJECT_LIMIT = 100;
const LEGACY_MEMBERSHIP_LIMIT = 2000;

/** Selector over the server cache, never another writable project store. */
export function useProjectMemberships(): Record<string, string> {
  const { data } = useChatProjects();
  return useMemo(() => Object.fromEntries(data?.memberships.map(item => [item.chat_id, item.project_id]) ?? []), [data]);
}

export function hasLegacyProjects(): boolean {
  return localStorage.getItem('bs_mock_projects') !== null;
}

/** The automatic migration reads legacy metadata; the original keys survive. */
export function readLegacyProjects(): {
  projects: Array<{ legacy_id: string; name: string; created_at?: string }>;
  memberships: Array<{ chat_id: string; legacy_project_id: string }>;
  skipped: number;
  invalid: Array<{ id: string; status: string }>;
} {
  const projectText = localStorage.getItem('bs_mock_projects') ?? '[]';
  const memberText = localStorage.getItem('bs_mock_project_chats') ?? '{}';
  if (projectText.length + memberText.length > 4 * 1024 * 1024) throw new Error('Legacy projects exceed the migration size limit');
  const raw: unknown = JSON.parse(projectText);
  const members: unknown = JSON.parse(memberText);
  if (!Array.isArray(raw) || !members || typeof members !== 'object' || Array.isArray(members)) throw new Error('Invalid legacy projects');
  const invalid: Array<{ id: string; status: string }> = [];
  const projects = raw.flatMap((value: unknown, index) => {
    if (!value || typeof value !== 'object' || !('id' in value) || !('name' in value) ||
        typeof value.id !== 'string' || !value.id || value.id.length > 255 || typeof value.name !== 'string' || !value.name.trim() || value.name.trim().length > 30) { invalid.push({ id: `#${index + 1}`, status: 'invalid_local_data' }); return []; }
    const created = 'createdAt' in value && typeof value.createdAt === 'number' ? new Date(value.createdAt) : undefined;
    return [{ legacy_id: value.id, name: value.name.trim(), ...(created && Number.isFinite(created.getTime()) ? { created_at: created.toISOString() } : {}) }];
  });
  const memberships = Object.entries(members).flatMap(([chat_id, legacy_project_id]) => {
    if (/^[A-Za-z0-9_-]{1,255}$/.test(chat_id) && chat_id !== 'new' && typeof legacy_project_id === 'string' && legacy_project_id.length > 0 && legacy_project_id.length <= 255) return [{ chat_id, legacy_project_id }];
    invalid.push({ id: chat_id, status: 'invalid_local_data' }); return [];
  });
  // One import request carries the whole record; the server caps it at 100 / 2000.
  for (const extra of projects.slice(LEGACY_PROJECT_LIMIT)) invalid.push({ id: extra.legacy_id, status: 'invalid_local_data' });
  const kept = new Set(projects.slice(0, LEGACY_PROJECT_LIMIT).map(project => project.legacy_id));
  const keptMembers = memberships.filter(member => kept.has(member.legacy_project_id));
  for (const extra of keptMembers.slice(LEGACY_MEMBERSHIP_LIMIT)) invalid.push({ id: extra.chat_id, status: 'invalid_local_data' });
  return { projects: projects.slice(0, LEGACY_PROJECT_LIMIT), memberships: keptMembers.slice(0, LEGACY_MEMBERSHIP_LIMIT), skipped: invalid.length, invalid };
}
