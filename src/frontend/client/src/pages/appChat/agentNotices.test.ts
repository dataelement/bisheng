import { parseAgentNotices } from './agentNotices';
import { normalizeAppChatFile } from './appChatFileUtils';

describe('F078 agent notices', () => {
    it('reads notice codes from a JSON string extra', () => {
        expect(parseAgentNotices('{"agent_notices":["code_executor_missing"]}')).toEqual(['code_executor_missing']);
    });

    it('reads notice codes from an object extra', () => {
        expect(parseAgentNotices({ agent_notices: ['deliverables_failed', 3] })).toEqual(['deliverables_failed']);
    });

    it.each([undefined, null, '', 'not json', '{"source": 1}', 42])('returns no notices for %p', (extra) => {
        expect(parseAgentNotices(extra)).toEqual([]);
    });
});

describe('F078 deliverable file cards', () => {
    it('maps a deliverable descriptor to the card name and download path', () => {
        expect(
            normalizeAppChatFile({ file_name: 'weekly-report.docx', file_url: '/api/v1/agent-runtime/files/c1/f1' })
        ).toEqual({ name: 'weekly-report.docx', path: '/api/v1/agent-runtime/files/c1/f1' });
    });
});
