import { beforeEach, describe, expect, it, vi } from 'vitest';
import { instantiateAssistantTemplate, type AssistantTemplateDraft } from '@/pages/BuildPage/assistantTemplate';

const api = vi.hoisted(() => ({ create: vi.fn(), save: vi.fn() }));
vi.mock('@/controllers/API/assistant', () => ({ createAssistantsApi: api.create, saveAssistanttApi: api.save }));
beforeEach(() => { vi.resetAllMocks(); api.create.mockResolvedValue({ id: 'new', model_name: 'default-model' }); api.save.mockResolvedValue({}); });

describe('assistant template instantiation', () => {
  it('copies long instructions and portable settings while retaining new identity and default model', async () => {
    const draft: AssistantTemplateDraft = {};
    const prompt = 'instructions '.repeat(500);
    const id = await instantiateAssistantTemplate({
      prompt, temperature: 0.3, guide_word: 'Hello', guide_question: ['Question'], max_token: 4000,
      id: 'source', user_id: 99, tenant_id: 3, model_name: 'source-model', knowledge_list: [4],
    }, { name: 'My assistant', desc: 'New description', url: '' }, draft);
    expect(id).toBe('new');
    expect(api.create).toHaveBeenCalledWith('My assistant', '', '');
    const saved = api.save.mock.calls[0][0];
    expect(saved).toMatchObject({ id: 'new', name: 'My assistant', desc: 'New description',
      model_name: 'default-model', prompt, temperature: 0.3, guide_question: ['Question'],
      knowledge_list: [], tool_list: [], flow_list: [] });
    expect(saved).not.toHaveProperty('tenant_id');
    expect(saved).not.toHaveProperty('user_id');
  });

  it('retries saving the same draft when configuration save failed', async () => {
    const draft: AssistantTemplateDraft = {};
    api.save.mockRejectedValueOnce(new Error('Save failed'));
    await expect(instantiateAssistantTemplate({ prompt: 'Hello' }, { name: 'New', desc: '', url: '' }, draft))
      .rejects.toThrow('Save failed');
    expect(draft.id).toBe('new');
    await instantiateAssistantTemplate({ prompt: 'Hello' }, { name: 'Retry name', desc: '', url: '' }, draft);
    expect(api.create).toHaveBeenCalledTimes(1);
    expect(api.save).toHaveBeenLastCalledWith(expect.objectContaining({ id: 'new', name: 'Retry name' }));
  });
});
