import { getAgentMessages } from './chatApi';
import request from './request';

jest.mock('./request', () => ({ __esModule: true, default: { get: jest.fn() } }));

it('restores the inline references and folder paths from a shared workbench history', async () => {
    const composerReferences = [
        { kind: 'skill', label: 'Web report', offset: 0 },
        { kind: 'space', label: '#Library', offset: 2 },
        { kind: 'space', label: '#Reports', offset: 2, is_tag: true },
    ];
    const files = [{ file_id: 'data', name: 'data.csv', relative_path: 'inputs/data.csv' }];
    jest.mocked(request.get).mockResolvedValue({ data: [
        { message_id: 1, category: 'question', message: { query: 'Old question' } },
        {
            message_id: 2,
            category: 'question',
            message: {
                query: '📊 Show the totals',
                composer_references: [
                    ...composerReferences,
                    { kind: 'unknown', label: 'Ignored', offset: 0 },
                    { kind: 'skill', label: 'Invalid tag', offset: 0, is_tag: true },
                ],
                files,
            },
        },
    ] });

    const messages = await getAgentMessages('conversation', 'share');

    expect(request.get).toHaveBeenCalledWith('/api/v1/workstation/messages/conversation/agent', { headers: { 'share-token': 'share' } });
    expect(messages[0]).toMatchObject({ text: 'Old question' });
    expect(messages[0].composerReferences).toBeUndefined();
    expect(messages[1]).toMatchObject({ text: '📊 Show the totals', composerReferences, files });
});
