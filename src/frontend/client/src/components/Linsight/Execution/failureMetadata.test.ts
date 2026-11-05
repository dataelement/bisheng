import { mergeStepFrames, mergedStepRenderEqual } from './stepTree';
import { foldStepFrame } from './stepFold';
import type { ExecStepEventData } from './execTypes';

const target = { version: 1, knowledge_id: '7', kind: 'space', name: 'Policies' };
const failure = { version: 1, failure_id: 'failure-one', category: 'model_service', occurred_at: '2026-11-05T08:00:00Z' };
const start: ExecStepEventData = { call_id: 'call-1', name: 'search_knowledge_base', step_type: 'knowledge', status: 'start', params: { knowledge_id: '7' }, extra_info: { knowledge_target: target } };

describe('task metadata snapshots', () => {
    it('retains the target across end replacement and the failure across replay', () => {
        const folded = foldStepFrame(start, { call_id: 'call-1', status: 'end', extra_info: { failure_info: failure } });
        const [step] = mergeStepFrames([folded]);
        expect(step.extraInfo).toMatchObject({ knowledge_target: target, failure_info: failure });
        expect(step.running).toBe(false);
        expect(step.callId).toBe('call-1');
    });
    it('updates the shared row and group comparison on visible metadata alone', () => {
        const [a] = mergeStepFrames([start]);
        const [b] = mergeStepFrames([{ ...start, extra_info: { knowledge_target: { ...target, name: 'Updated' } } }]);
        expect(mergedStepRenderEqual(a, b)).toBe(false);
        expect(mergedStepRenderEqual(a, { ...a, extraInfo: JSON.parse(JSON.stringify(a.extraInfo)) })).toBe(true);
    });
    it('preserves repeated actual calls to the same target', () => {
        expect(mergeStepFrames([start, { ...start, call_id: 'call-2' }])).toHaveLength(2);
    });
});
