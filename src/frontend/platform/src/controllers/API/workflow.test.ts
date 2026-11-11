import { afterEach, describe, expect, it, vi } from 'vitest';
import axios from '../request';
import { createWorkflowApi, getPlatformAgentCapabilities, saveWorkflow, updateVersion } from './workflow';

vi.mock('../request', () => ({ default: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));

describe('platform Agent capabilities', () => {
    afterEach(() => vi.clearAllMocks());

    it.each([true, false, undefined])('preserves the server tenant-mode flag: %s', async multiTenant => {
        vi.mocked(axios.get).mockResolvedValue({ workflow: { platform_agent_enabled: true, platform_agent_mode: 'mock', platform_agent_policy_revision: 'v1' }, multi_tenant_enabled: multiTenant });
        expect(await getPlatformAgentCapabilities()).toEqual({ platform_agent_enabled: true, platform_agent_mode: 'mock', platform_agent_policy_revision: 'v1', multi_tenant_enabled: multiTenant });
        expect(axios.get).toHaveBeenCalledWith('/api/v1/env');
    });
});

it('sends creation and draft revision headers through the existing endpoints', async () => {
    await createWorkflowApi('workflow', '', '', undefined, 'same-request');
    expect(axios.post).toHaveBeenCalledWith('/api/v1/workflow/create', expect.objectContaining({ name: 'workflow' }),
        { headers: { 'Idempotency-Key': 'same-request' } });
    const draft = { id: 'flow', name: 'draft', description: '', nodes: [], edges: [], viewport: { x: 0, y: 0, zoom: 1 } };
    await saveWorkflow(1, draft, 'old-revision');
    expect(axios.put).toHaveBeenCalledWith('/api/v1/workflow/versions/1', draft, { headers: { 'If-Match': 'old-revision' } });
    const rename = { name: 'new name', description: '', data: null };
    await updateVersion('1', rename, 'new-revision');
    expect(axios.put).toHaveBeenCalledWith('/api/v1/workflow/versions/1', rename, { headers: { 'If-Match': 'new-revision' } });
});

it('keeps management creation scoped and typed without a general creation grant', async () => {
    await createWorkflowApi('workflow', '', '', { flow_type: 35 }, 'workflow-only-request', true);
    expect(axios.post).toHaveBeenLastCalledWith('/api/v1/workflow/create', expect.objectContaining({ flow_type: 10 }), {
        headers: { 'Idempotency-Key': 'workflow-only-request' },
        params: { scope: 'workflow_management' },
    });
});
