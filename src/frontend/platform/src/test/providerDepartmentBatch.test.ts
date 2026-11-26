import { describe, expect, it, vi } from 'vitest';
import request from '@/controllers/request';
import { createExternalDepartmentBatch, getExternalDepartmentBatchStatus, listProviderModels, previewDepartmentPreset } from '@/controllers/API/departmentKnowledgeSpace';

vi.mock('@/controllers/request', () => ({ default: { post: vi.fn(), get: vi.fn() } }));
const pin = { headers: { 'X-Management-Tenant': '31' } };
const selection = { summary_model_id: 's', embedding_model_id: 'm', vision_model_id: 'v', chunk_size: 512, overlap: 64, extract_template_kb_id: 'tpl' };

describe('department provisioning', () => {
  it('previews the chosen models for the selected department and submits the same frozen summary with a tenant pin', async () => {
    const summary = { preset_revision: 8, ...selection };
    vi.mocked(request.post).mockResolvedValueOnce({ preset_summary: summary }).mockResolvedValueOnce({ items: [
      { department_id: 3, operation_id: 'a', state: 'succeeded', authorization: 'confirmed' },
      { department_id: 5, admission: 'conflict', authorization: 'not_confirmed' },
    ] });
    const preview = await previewDepartmentPreset(31, 3, selection);
    const rows = await createExternalDepartmentBatch(31, [3, 5], 'original-key', preview, selection);
    expect(request.post).toHaveBeenCalledWith('/api/v1/knowledge/space/department/provider-preview', { department_id: 3, provider_selection: selection }, pin);
    expect(request.post).toHaveBeenCalledWith('/api/v1/knowledge/space/department/batch-create', {
      provider_key: 'weknora', request_key: 'original-key', preset_summary: summary, provider_selection: selection, items: [{department_id: 3}, {department_id: 5}],
    }, pin);
    expect(rows.map(row => row.status)).toEqual(['confirmed', 'failed']);
  });
  it('rejects a preview that does not describe the chosen models', async () => {
    vi.mocked(request.post).mockResolvedValueOnce({ preset_summary: { ...selection, chunk_size: 800 } });
    await expect(previewDepartmentPreset(31, 3, selection)).rejects.toThrow();
  });
  it('lists WeKnora models under the pinned tenant and refuses malformed entries', async () => {
    const models = { chat: [{ id: 's', name: 'qwen', display_name: 'Qwen' }], embedding: [{ id: 'm', name: 'bge', display_name: 'BGE', dimension: 1024 }], vision: [] };
    vi.mocked(request.get).mockResolvedValueOnce(models).mockResolvedValueOnce({ ...models, embedding: [{ id: 'm', name: 'bge', display_name: 'BGE' }] });
    await expect(listProviderModels(31)).resolves.toEqual(models);
    expect(request.get).toHaveBeenCalledWith('/api/v1/knowledge/space/provider-models', pin);
    await expect(listProviderModels(31)).rejects.toThrow();
  });
  it('reopens via a read, never retries creation; missing or contradictory receipts are not successes', async () => {
    vi.mocked(request.post).mockResolvedValueOnce({items: [{department_id: 3, state: 'pending', authorization: 'confirmed'}, {department_id: 99, state:'succeeded', authorization:'confirmed'}]});
    const rows = await getExternalDepartmentBatchStatus(31, [3, 5], 'original-key');
    expect(request.post).toHaveBeenLastCalledWith('/api/v1/knowledge/space/department/batch-status', {request_key:'original-key', department_ids:[3,5]}, pin);
    expect(rows.map(row => row.status)).toEqual(['unconfirmed', 'unconfirmed']);
  });
});
