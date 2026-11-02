import { finishStoppedAppMessage, isAppMessageStopped, stopAppMessages } from './appMessageStop';

const answer = { id: 'runoutput', category: 'stream_msg', is_bot: true, end: false,
    message: '1. partial', reasoning_log: 'thinking' };

test('manual stop preserves partial content and completed rounds', () => {
    const completed = { ...answer, id: 'old', end: true };
    const question = { ...answer, category: 'question', is_bot: false };
    const messages = [completed, question, answer];
    const result = stopAppMessages(messages);
    expect(result[0]).toBe(completed);
    expect(result[1]).toBe(question);
    expect(result[2]).toEqual({ ...answer, end: true, stopped: true });
    expect(messages[2].end).toBe(false);
});

test('completed output in a running workflow retains its completion state', () => {
    const completed = { ...answer, end: true };
    expect(stopAppMessages([completed])[0]).toBe(completed);
});

test.each(['tool', 'flow', 'knowledge'])('pending %s cards settle as interrupted', (category) => {
    expect(stopAppMessages([{ ...answer, category }])[0]).toMatchObject({ end: true, interrupted: true });
});

test('the terminal workflow ID attaches to the frozen partial answer', () => {
    const messages = stopAppMessages([answer]);
    expect(finishStoppedAppMessage(messages, { type: 'end', category: 'stream_msg', message_id: 12,
        message: { unique_id: 'run', output_key: 'output', msg: 'late replacement' } })[0])
        .toEqual({ ...answer, id: 12, message_id: 12, chat_source_message_id: 12, end: true, stopped: true });
});

test('the terminal assistant ID attaches while reasoning and tool IDs stay separate', () => {
    const messages = stopAppMessages([answer]);
    for (const category of ['tool', 'flow', 'knowledge', 'reasoning_answer']) {
        expect(finishStoppedAppMessage(messages, { type: 'end', category, message_id: 8 })).toBe(messages);
    }
    expect(finishStoppedAppMessage(messages, { type: 'end', category: 'answer', message_id: 12 })[0].id).toBe(12);
});

test('history uses the backend interrupted-response marker', () => {
    expect(isAppMessageStopped({ remark: 'break_answer' })).toBe(true);
    expect(isAppMessageStopped({ stopped: true })).toBe(true);
    expect(isAppMessageStopped({ remark: '' })).toBe(false);
    expect(isAppMessageStopped({})).toBe(false);
});


test('a terminal ID belongs to the current round', () => {
    const previous = { ...answer, stopped: true, end: true };
    const question = { ...answer, category: 'question', is_bot: false };
    const messages = [previous, question];
    expect(finishStoppedAppMessage(messages, { type: 'end', category: 'answer', message_id: 99 })[0]).toBe(previous);
});
