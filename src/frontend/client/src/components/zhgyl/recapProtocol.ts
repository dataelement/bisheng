import { advisorScenes, type AdvisorScene, type WorkspaceScene } from './scenes';
export const recapStatuses = ['done', 'running', 'waiting', 'pending', 'error', 'empty', 'skipped'] as const;
export type RecapStatus = typeof recapStatuses[number];
export interface RecapNode { title: string; summary: string; status: RecapStatus; details: string[] }
export interface BusinessRecord { version: 1; mode: 'execution_recap'; scene: AdvisorScene; nodes: RecapNode[]; demo?: boolean; conditions?: string[] }
export type RecapRead = { kind: 'other' } | { kind: 'pending' } | { kind: 'invalid' } | { kind: 'valid'; record: BusinessRecord };

/** Limit untrusted model metadata before rendering. No HTML or executable content is accepted. */
export function readBusinessRecap(raw: string, scene: WorkspaceScene, className = ''): RecapRead {
  if (scene === 'select' || !/(?:^|\s)language-business(?:-process)?(?:\s|$)/.test(className)) return { kind: 'other' };
  const legacy = !className.includes('language-business-process');
  if (legacy && ((scene && scene !== 'transport') || !/"scene"\s*:\s*"transport"/.test(raw.slice(0, 1024)) || !/"mode"\s*:\s*"execution_recap"/.test(raw.slice(0, 1024)))) return { kind: 'other' };
  if (raw.length > 30000) return { kind: 'invalid' };
  let value: unknown;
  try { value = JSON.parse(raw); } catch {
    if ((scene === 'transport' || !scene && /"scene"\s*:\s*"transport"/.test(raw.slice(0, 1024))) && raw.trimEnd().endsWith(']')) {
      try { value = JSON.parse(`${raw.trimEnd()}}`); } catch { return { kind: 'pending' }; }
    } else return { kind: 'pending' };
  }
  if (!value || typeof value !== 'object') return { kind: 'invalid' };
  const record = value as Record<string, unknown>;
  if (record.version !== 1 || record.mode !== 'execution_recap' || !!scene && record.scene !== scene || !advisorScenes.includes(record.scene as AdvisorScene) || !Array.isArray(record.nodes) || record.nodes.length < 1 || record.nodes.length > 12) return { kind: 'invalid' };
  if (record.conditions !== undefined && (!Array.isArray(record.conditions) || !record.conditions.every(value => typeof value === 'string' && value.length <= 700))) return { kind: 'invalid' };
  const valid = record.nodes.every((node: unknown) => {
    if (!node || typeof node !== 'object') return false;
    const item = node as Record<string, unknown>;
    return typeof item.title === 'string' && item.title.length <= 100 && typeof item.summary === 'string' && item.summary.length <= 600 && recapStatuses.includes(item.status as RecapStatus) && Array.isArray(item.details) && item.details.every(detail => typeof detail === 'string' && detail.length <= 700);
  });
  return valid ? { kind: 'valid', record: record as unknown as BusinessRecord } : { kind: 'invalid' };
}
