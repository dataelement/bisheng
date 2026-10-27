import { expect, it } from 'vitest';
import { workflowStreamForHost, historyForHost, messagesForPresentation } from './index';

it('keeps SEC agent deliverables and notices through stream completion and history', () => {
  const options = { mode: 'workflow' as const, sessionKey: 'sec-test' };
  const files = [{ file_id: 'report', file_name: 'report.docx', file_url: '/report.docx', format_error: 'invalid_zip' }];
  const extra = JSON.stringify({ agent_notices: ['deliverables_failed'] });
  const started = workflowStreamForHost([], { category: 'stream_msg', type: 'stream', message: { unique_id: 'agent', output_key: 'answer', msg: 'Draft' } }, options.sessionKey);
  const ended = workflowStreamForHost(started, { category: 'stream_msg', type: 'end', message_id: 42, message: { unique_id: 'agent', output_key: 'answer', msg: 'Report ready' }, files, extra }, options.sessionKey);
  const live = messagesForPresentation(ended, options)[0];
  const restored = messagesForPresentation(historyForHost([{ id: 42, category: 'stream_msg', is_bot: true, message: 'Report ready', files: JSON.stringify(files), extra }], options), options)[0];
  for (const message of [live, restored]) {
    expect(message.text).toBe('Report ready');
    expect(message.files[0]).toMatchObject({ id: 'report', name: 'report.docx', url: '/report.docx', raw: { format_error: 'invalid_zip' } });
    expect(message.raw.extra).toBe(extra);
  }
});
