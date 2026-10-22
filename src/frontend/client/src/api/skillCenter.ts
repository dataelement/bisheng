import request from './request';
import { SkillRequestError, type SkillRecord } from '~/components/Skills/types';

const SKILL_API = '/api/v1/linsight/skill';

interface Envelope<T> {
  status_code: number;
  status_message?: string;
  data: T;
}

interface ApiCard {
  id: number;
  name: string;
  display_name: string;
  description: string;
  enabled: boolean;
  content_hash: string;
  bundle_missing: boolean;
  update_time?: string | null;
  preview?: string;
  source_text?: string;
  files?: { path: string }[];
}

export interface SkillCenterData {
  personal: SkillRecord[];
  enterprise: SkillRecord[];
  personalCount: number;
  enterpriseCount: number;
}

export interface SkillUsage {
  count: number;
  usedBytes: number;
  countLimit: number;
  bytesLimit: number;
}

function toRecord(row: ApiCard, source: SkillRecord['source']): SkillRecord {
  return {
    id: row.id,
    name: row.name,
    displayName: row.display_name || row.name,
    description: row.description || '',
    source,
    enabled: Boolean(row.enabled),
    contentHash: row.content_hash,
    bundleMissing: Boolean(row.bundle_missing),
    updatedAt: row.update_time || '',
    preview: row.preview || '',
    sourceText: row.source_text || '',
    files: (row.files || []).map((file) => file.path),
  };
}

function unwrap<T>(body: Envelope<T>): T {
  if (body?.status_code !== 200) {
    const data = body?.data;
    throw new SkillRequestError(
      body?.status_code,
      data && typeof data === 'object' ? data as Record<string, unknown> : undefined,
      body?.status_message,
    );
  }
  return body.data;
}

export async function getSkillCenter(keyword?: string, tab: 'personal' | 'enterprise' = 'personal'): Promise<SkillCenterData> {
  const response = await request.get<Envelope<{
    personal: ApiCard[];
    enterprise: ApiCard[];
    personal_count: number;
    enterprise_count: number;
  }>>(SKILL_API + '/center', { params: { tab, keyword: keyword || undefined } });
  const data = unwrap(response);
  return {
    personal: (data.personal || []).map((row) => toRecord(row, 'personal')),
    enterprise: (data.enterprise || []).map((row) => toRecord(row, 'platform')),
    personalCount: data.personal_count,
    enterpriseCount: data.enterprise_count,
  };
}

export async function getSkillDetail(skillId: number): Promise<SkillRecord> {
  // A missing bundle is one skill, not a service outage. The dialog explains it.
  const response = await request.get<Envelope<ApiCard>>(`${SKILL_API}/personal/${skillId}`, {
    skipMaintenance: true,
  });
  const row = unwrap(response);
  return toRecord(row, 'personal');
}

/** Raw text of one file in the bundle. Enterprise and personal skills share this path. */
export async function getSkillFile(skillId: number, path: string): Promise<string> {
  const response = await request.get<Envelope<{ path: string; content: string }>>(
    `${SKILL_API}/personal/${skillId}/file`,
    { params: { path }, skip403Redirect: true, skipMaintenance: true },
  );
  return unwrap(response).content ?? '';
}

export async function getPersonalSkillUsage(): Promise<SkillUsage> {
  const response = await request.get<Envelope<{
    count: number;
    used_bytes: number;
    count_limit: number;
    bytes_limit: number;
  }>>(`${SKILL_API}/personal/usage`);
  const data = unwrap(response);
  return {
    count: data.count,
    usedBytes: data.used_bytes,
    countLimit: data.count_limit,
    bytesLimit: data.bytes_limit,
  };
}

export async function findPersonalSkillByImport(importId: string): Promise<SkillRecord | null> {
  const response = await request.get<Envelope<ApiCard>>(
    `${SKILL_API}/personal/import/${encodeURIComponent(importId)}`,
  );
  if (response?.status_code === 11053) return null;
  return toRecord(unwrap(response), 'personal');
}

export interface SkillUploadCheck {
  name: string;
  displayName: string;
  description: string;
  size: number;
  files: string[];
}

/** Parse and validate one file. A passing result is not saved. */
export async function checkPersonalSkill(file: File, skillId?: number): Promise<SkillUploadCheck> {
  const form = new FormData();
  form.append('file', file);
  if (skillId) form.append('skill_id', String(skillId));
  const response = await request.postMultiPart(
    `${SKILL_API}/personal/check`,
    form,
    { showError: false },
  ) as Envelope<{
    name: string;
    display_name: string;
    description: string;
    size: number;
    files?: { path: string }[];
  }>;
  const data = unwrap(response);
  return {
    name: data.name,
    displayName: data.display_name || data.name,
    description: data.description || '',
    size: data.size,
    files: (data.files || []).map((item) => item.path),
  };
}

function skillForm(file: File, importId: string, expectedHash?: string): FormData {
  const form = new FormData();
  form.append('file', file);
  form.append('import_id', importId);
  if (expectedHash) form.append('expected_content_hash', expectedHash);
  return form;
}

export async function createPersonalSkill(file: File, importId: string): Promise<SkillRecord> {
  const response = await request.postMultiPart(
    `${SKILL_API}/personal`,
    skillForm(file, importId),
    { showError: false },
  ) as Envelope<ApiCard>;
  return toRecord(unwrap(response), 'personal');
}

export async function overwritePersonalSkill(
  skillId: number,
  file: File,
  importId: string,
  expectedHash: string,
): Promise<SkillRecord> {
  const response = await request.postMultiPart(
    `${SKILL_API}/personal/${skillId}/overwrite`,
    skillForm(file, importId, expectedHash),
    { showError: false },
  ) as Envelope<ApiCard>;
  return toRecord(unwrap(response), 'personal');
}

export async function setPersonalSkillEnabled(skillId: number, enabled: boolean): Promise<SkillRecord> {
  // A denied toggle stays on this page. The interceptor explains a 403; bouncing
  // to the new-chat route would hide the skill the person was just changing.
  const response = await request.patch<Envelope<ApiCard>>(
    `${SKILL_API}/personal/${skillId}/status`,
    { enabled },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- skip403Redirect is an ErrorOptions extra
    { skip403Redirect: true } as any,
  );
  return toRecord(unwrap(response), 'personal');
}

export async function deletePersonalSkill(skillId: number): Promise<void> {
  unwrap(await request.delete<Envelope<Record<string, never>>>(`${SKILL_API}/personal/${skillId}`));
}
