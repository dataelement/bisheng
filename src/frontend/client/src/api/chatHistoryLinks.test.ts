import request from './request';
import { getAgentMessages } from './chatApi';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));

it('restores question links across answers, task turns and a reloaded failure card', async () => {
    (request.get as jest.Mock).mockResolvedValue({ data: [
        { message_id: 1, category: 'question', is_bot: false, message: { query: 'First question', files: [{ name: 'notes.txt' }] } },
        { message_id: 2, category: 'agent_answer', is_bot: true, message: { msg: 'Partial answer', events: [] }, extra: { error: true, error_code: 12046, error_type: 'rate_limit', reference_id: 'support-one' } },
        { message_id: 3, category: 'task', is_bot: true, message: 'Task answer', extra: { linsight_session_version_id: 'task-one' } },
        { message_id: 4, category: 'question', is_bot: false, message: { query: 'Next question' } },
        { message_id: 5, category: 'agent_answer', is_bot: true, message: { msg: 'Answer', events: [] } },
    ] });

    const messages = await getAgentMessages('chat', 'share');

    expect(messages.map(message => message.parentMessageId)).toEqual(['', '1', '1', '3', '4']);
    expect(messages[0].files?.[0].name).toBe('notes.txt');
    expect(messages[1]).toMatchObject({ text: 'Partial answer', errorType: 'rate_limit', referenceId: 'support-one' });
    expect(messages[2].linsightSessionVersionId).toBe('task-one');
    expect(request.get).toHaveBeenCalledWith(expect.any(String), { headers: { 'share-token': 'share' } });
});
