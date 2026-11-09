import { render } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useAssistantStore } from '@/store/assistantStore';
import type { AssistantDetail } from '@/types/assistant';
import ModelItem from '@/pages/BuildPage/flow/FlowNode/component/ModelItem';
import { toModelCascaderOptions, toModelCascaderValue, toGroupedModelOptions } from './modelOptions';

vi.mock('@/pages/ModelPage/manage', () => ({ useModel: () => ({ llmOptions: [{ value: 1, label: 'provider', children: [{ value: 11, label: 'new model' }] }] }) }));
vi.mock('@/controllers/API/finetune', () => ({ getLlmDefaultModel: vi.fn().mockResolvedValue({ model_id: 11 }) }));
vi.mock('@bisheng/ui', () => ({ Select: () => null }));
beforeEach(() => useAssistantStore.getState().destroy());

it('opening a workflow with a missing saved model never clears or replaces its slot', () => {
  const onChange = vi.fn();
  render(<ModelItem agent data={{ value: '000999', required: true }} onChange={onChange} onValidate={vi.fn()} i18nPrefix="model." />);
  expect(onChange).not.toHaveBeenCalled();
});

it('assistant retains the full authoritative id set and original model bytes during unrelated edits', () => {
  const detail = { id: 1, model_name: '000999', knowledge_ids: [10, 20, 30], knowledge_list: [{ id: 10, type: 3, name: 'visible' }], reference_states: [
    { slot_key: 'knowledge_list', target_type: 'knowledge_space', target_id: '20', state: 'invalid_deleted', is_valid: false },
    { slot_key: 'knowledge_list', target_type: 'knowledge_space', target_id: '30', state: 'invalid_legacy', is_valid: false },
  ] } as unknown as AssistantDetail;
  useAssistantStore.getState().setAssistantDetail(detail);
  useAssistantStore.getState().dispatchAssistant('setPrompt', { prompt: 'only this changed' });
  const saved = useAssistantStore.getState().assistantState;
  expect(saved.model_name).toBe('000999');
  expect(saved.knowledge_list?.map(item => item.id)).toEqual([10, 20, 30]);
  expect(saved.knowledge_list?.[1].name).toBeUndefined();
  expect(saved.knowledge_list?.[0].type).toBe(3);
});

it('missing saved Cascader model has a disabled placeholder and a controlled path', () => {
  const options = toModelCascaderOptions([], '000999', 'Unavailable');
  expect(options).toEqual([{ value: '__saved_model__:000999', label: 'Unavailable', disabled: true, children: [{ value: '000999', label: 'Unavailable: 000999', disabled: true }] }]);
  expect(toModelCascaderValue('000999', [], true)).toEqual(['__saved_model__:000999', '000999']);
  expect(toGroupedModelOptions([], '000999', 'Unavailable')).toEqual([{ value: '000999', label: 'Unavailable: 000999', disabled: true }]);
});

it('repairing a single assistant slot preserves every other hidden id and type', () => {
  const detail = { id: 1, model_name: '11', knowledge_ids: [10, 20, 30], knowledge_list: [{ id: 10, type: 0, name: 'old type' }, { id: 20, type: 1, name: 'QA' }] } as AssistantDetail;
  useAssistantStore.getState().setAssistantDetail(detail);
  const before = useAssistantStore.getState().assistantState;
  useAssistantStore.getState().dispatchAssistant('setting', { knowledge_list: [before.knowledge_list![0], { id: 40, name: 'new space', type: 3 }, before.knowledge_list![2]] });
  expect(useAssistantStore.getState().assistantState.knowledge_list).toEqual([{ id: 10, type: 0, name: 'old type' }, { id: 40, name: 'new space', type: 3 }, { id: 30 }]);
  expect(useAssistantStore.getState().assistantState.model_name).toBe('11');
});
