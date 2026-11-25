import { describe, expect, it, vi } from 'vitest';
import request from '@/controllers/request';
import { createExternalDepartmentBatch, getExternalDepartmentBatchStatus, previewDepartmentPreset } from '@/controllers/API/departmentKnowledgeSpace';

vi.mock('@/controllers/request', () => ({ default: { post: vi.fn() } }));
const pin = { headers: { 'X-Management-Tenant': '31' } };

describe('department provisioning', () => {
  it('previews for the selected department and submits the same frozen summary with a tenant pin', async () => {
    const summary = { preset_revision: 8, embedding_model_id: 'm' };
    vi.mocked(request.post).mockResolvedValueOnce({ preset_summary: summary }).mockResolvedValueOnce({ items: [
      { department_id: 3, operation_id: 'a', state: 'succeeded', authorization: 'confirmed' },
      { department_id: 5, admission: 'conflict', authorization: 'not_confirmed' },
    ] });
    const preview = await previewDepartmentPreset(31, 3);
    const rows = await createExternalDepartmentBatch(31, [3, 5], 'original-key', preview);
    expect(request.post).toHaveBeenCalledWith('/api/v1/knowledge/space/department/provider-preview', { department_id: 3 }, pin);
    expect(request.post).toHaveBeenCalledWith('/api/v1/knowledge/space/department/batch-create', {
      provider_key: 'weknora', request_key: 'original-key', preset_summary: summary, items: [{department_id: 3}, {department_id: 5}],
    }, pin);
    expect(rows.map(row => row.status)).toEqual(['confirmed', 'failed']);
  });
  it('reopens via a read, never retries creation; missing or contradictory receipts are not successes', async () => {
    vi.mocked(request.post).mockResolvedValueOnce({items: [{department_id: 3, state: 'pending', authorization: 'confirmed'}, {department_id: 99, state:'succeeded', authorization:'confirmed'}]});
    const rows = await getExternalDepartmentBatchStatus(31, [3, 5], 'original-key');
    expect(request.post).toHaveBeenLastCalledWith('/api/v1/knowledge/space/department/batch-status', {request_key:'original-key', department_ids:[3,5]}, pin);
    expect(rows.map(row => row.status)).toEqual(['unconfirmed', 'unconfirmed']);
  });
});
