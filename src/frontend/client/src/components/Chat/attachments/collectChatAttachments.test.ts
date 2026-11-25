import { collectChatAttachments, toChatArtifact } from './collectChatAttachments';

jest.mock('~/pages/knowledge/FilePreview/previewUrlUtils', () => ({ resolveKnowledgePreviewUrl: (url: string) => url }));
jest.mock('~/api/chatApi', () => ({ getAttachmentUrl: jest.fn() }));

describe('conversation attachment collection', () => {
  it('keeps files across turns and replaces renewed URLs by stable file identity', () => {
    const files = collectChatAttachments([
      { files: [{ file_id: 'a', name: 'report.pdf', file_url: '/old' }] },
      { files: [{ file_id: 'a', name: 'report.pdf', file_url: '/renewed' }, { file_id: 'b', name: 'report.pdf', file_url: '/other' }] },
    ]);
    expect(files).toHaveLength(2);
    expect(files[0]).toMatchObject({ file_id: 'a', directUrl: '/renewed' });
    expect(files[1].file_id).toBe('b');
  });
  it('skips incomplete records and stale local upload paths', () => {
    expect(collectChatAttachments([{ files: [{ name: 'empty' }, { name: 'local', filepath: 'blob:old' }] }])).toEqual([]);
  });
  it('fetches a generated file of an answer with the row file_id, not the workspace id', () => {
    // F004 design §7 item 11: `file_id` is the answer's own copy.
    const copied = { file_id: 'copy-1', workspace_file_id: 'live-1', file_name: 'a.md', path: 'output/a.md', object_name: 'chat/7/answers/r1/live-1.md' };
    expect(toChatArtifact(copied, 'c1')).toMatchObject({ file_id: 'copy-1', attachment: { conversationId: 'c1', fileId: 'copy-1' } });
    expect(toChatArtifact(copied, 'c1')?.attachment).not.toHaveProperty('run');
    // The copy failed on the backend: the row keeps the event id and still resolves.
    const kept = { file_id: 'live-2', file_name: 'b.md', path: 'output/b.md', object_name: 'workspace/c1/output/b.md' };
    expect(toChatArtifact(kept, 'c1')).toMatchObject({ file_id: 'live-2', attachment: { conversationId: 'c1', fileId: 'live-2' } });
  });
  it('keeps the original document format for uploaded chat files', () => {
    expect(toChatArtifact({ filename: 'notes.docx', path: '/tmp-dir/notes.docx' })).toEqual({
      file_id: '/tmp-dir/notes.docx', file_name: 'notes.docx', file_url: '/tmp-dir/notes.docx', directUrl: '/tmp-dir/notes.docx',
    });
  });
});
