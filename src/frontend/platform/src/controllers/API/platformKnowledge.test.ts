import { describe, expect, it, vi } from 'vitest';
import request from '../request';
import { getKnowledgeCapabilities, getPlatformKnowledge } from './platformKnowledge';

vi.mock('../request', () => ({ default: { get: vi.fn() } }));

describe('platform knowledge API', () => {
    it.each([true, false, undefined])('preserves tenant capability %s', async multi_tenant_enabled => {
        vi.mocked(request.get).mockResolvedValue({ workflow: { platform_knowledge_mode: 'mock' }, multi_tenant_enabled });
        expect(await getKnowledgeCapabilities()).toMatchObject({ multi_tenant_enabled, platform_knowledge_mode: 'mock' });
    });

    it('encodes the resource identifier', async () => {
        await getPlatformKnowledge('flow', 'mock:maintenance');
        expect(request.get).toHaveBeenLastCalledWith('/api/v1/workflow/platform-knowledge/mock%3Amaintenance', {
            params: { workflow_id: 'flow' },
        });
    });
});
