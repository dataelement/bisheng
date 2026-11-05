import { knowledgeStepTitle } from './knowledgeStepTitle';

const localize = (key: string, options?: { 0?: string }) => `${key}${options?.[0] ? `:${options[0]}` : ''}`;
const step = { name: 'search_knowledge_base', params: { knowledge_id: '7' } };

describe('knowledge step titles', () => {
    it('uses the same generic localized title before and after completion', () => {
        expect(knowledgeStepTitle(step, localize)).toBe('com_linsight.knowledge_target_knowledge_base');
    });
    it('uses a validated target snapshot, never model-generated parameter names', () => {
        expect(knowledgeStepTitle({ ...step, params: { knowledge_id: '7', knowledge_name: 'Invented' } }, localize)).not.toContain('Invented');
        expect(knowledgeStepTitle({ ...step, extraInfo: { knowledge_target: { version: 1, knowledge_id: '7', kind: 'space', name: 'Visible' } } }, localize)).toBe('com_linsight.knowledge_target_space_named:Visible');
    });
    it('keeps personal names private and rejects a mismatched target', () => {
        expect(knowledgeStepTitle({ ...step, extraInfo: { knowledge_target: { version: 1, knowledge_id: '7', kind: 'personal', name: 'Private' } } }, localize)).toBe('com_linsight.knowledge_target_personal');
        expect(knowledgeStepTitle({ ...step, extraInfo: { knowledge_target: { version: 1, knowledge_id: '8', kind: 'space', name: 'Wrong' } } }, localize)).toBe('com_linsight.knowledge_target_knowledge_base');
    });
    it('waits for actual target parameters before displaying an authorized name', () => {
        expect(knowledgeStepTitle({ name: 'search_knowledge_base', extraInfo: { knowledge_target: { version: 1, knowledge_id: '7', kind: 'space', name: 'Not yet matched' } } }, localize)).toBe('com_linsight.knowledge_target_knowledge_base');
    });
});
