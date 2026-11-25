import request from '@/controllers/request';

const kinds = ['create_space', 'update_space_settings', 'upload', 'provider_transfer'] as const;
const phases = ['create', 'settings', 'projected', 'upload', 'reingest', 'cutover'] as const;
const states = ['pending', 'sending', 'waiting_remote', 'reconciling', 'applying', 'succeeded', 'failed', 'manual_review'] as const;
const maskedTarget = /^target-[0-9a-f]{16}$/;
const uuid = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
function known<T extends string>(value: unknown, values: readonly T[]): T | 'unknown' {
  return values.find(v => v === value) ?? 'unknown';
}
function integer(value: unknown, min = 0): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= min;
}
function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function record(raw: unknown, spaceId: number) {
  if (!object(raw) || raw.space_id !== spaceId || !integer(raw.generation) || !integer(raw.attempt) ||
      !integer(raw.capability_revision) || !Array.isArray(raw.version_ids) || !raw.version_ids.every(v => integer(v, 1))) {
    throw new Error('Invalid operation record');
  }
  // Cache only the read model used by the dialog, never raw upstream fields or response bodies.
  return {
    operationId: typeof raw.operation_id === 'string' && uuid.test(raw.operation_id) ? raw.operation_id : null,
    kind: known(raw.kind, kinds), phase: known(raw.phase, phases), state: known(raw.state, states),
    remoteTarget: typeof raw.remote_target === 'string' && maskedTarget.test(raw.remote_target) ? raw.remote_target : null,
    spaceId, versionIds: raw.version_ids as number[], generation: raw.generation, attempt: raw.attempt,
    capabilityRevision: raw.capability_revision,
    errorCode: raw.error_code === null ? null : known(raw.error_code, ['not_received', 'manual_review_required'] as const),
  };
}
export async function readProviderOperations(spaceId: number, page: number, pageSize: number, signal?: AbortSignal) {
  const raw = await request.get<unknown, unknown>(`/api/v1/knowledge/space/${spaceId}/provider-operations`, {
    params: { page, page_size: pageSize }, signal, showError: false,
  });
  if (!object(raw) || !integer(raw.total) || !Array.isArray(raw.data) || raw.data.length > pageSize || raw.data.length > raw.total) {
    throw new Error('Invalid operation history');
  }
  return { total: raw.total, data: raw.data.map(item => record(item, spaceId)) };
}
