import type { AgentEvent } from '~/api/chatApi';
import { askedQuestionData } from './askedQuestion';
import { groupEventsForDisplay } from './groupEvents';

const question = { call_id: 'c1', reason: '', questions: [{ id: 'q1', question: 'Which page?', options: ['Event page'] }] };
const asked = (extra: Partial<Extract<AgentEvent, { type: 'tool_call' }>> = {}): AgentEvent => ({
    type: 'tool_call',
    tool_call_id: 'c1',
    tool_name: 'ask_user',
    args: question,
    ...extra,
});
const tool: AgentEvent = { type: 'tool_call', tool_call_id: 't1', tool_name: 'write_file' };

describe('groupEventsForDisplay: ask_user', () => {
    it('an answered question is its own block between the tool groups', () => {
        const blocks = groupEventsForDisplay([tool, asked({ results: 'Event page', inflight: false }), tool]);
        expect(blocks.map((b) => b.kind)).toEqual(['group', 'question', 'group']);
    });

    it('an open question is not a tool step: the card above the input box asks it', () => {
        expect(groupEventsForDisplay([asked({ inflight: true })])).toEqual([]);
        expect(groupEventsForDisplay([tool, asked({ inflight: false })]).map((b) => b.kind)).toEqual(['group']);
    });
});

describe('askedQuestionData', () => {
    it('gives IntentRow the question and the answer', () => {
        const data = askedQuestionData(asked({ results: 'Event page' }) as Extract<AgentEvent, { type: 'tool_call' }>);
        expect(data.user_input).toBe('Event page');
        expect(data.call_id).toBe('c1');
        expect((data.params as { tool_calls: Array<{ args: { question: string } }> }).tool_calls[0].args.question).toBe(
            'Which page?',
        );
    });

    it('a stored call without arguments still shows its answer', () => {
        const data = askedQuestionData({ type: 'tool_call', tool_call_id: 'c2', tool_name: 'ask_user', results: 'x' });
        expect(data.user_input).toBe('x');
        expect(data.call_id).toBe('c2');
    });
});
