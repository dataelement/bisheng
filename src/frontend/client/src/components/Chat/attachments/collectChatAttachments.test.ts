import { collectChatAttachments, toChatArtifact } from './collectChatAttachments';

jest.mock('~/pages/knowledge/FilePreview/previewUrlUtils', () => ({ resolveKnowledgePreviewUrl: (url: string) => url }));

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
  it('keeps the original document format for uploaded chat files', () => {
    expect(toChatArtifact({ filename: 'notes.docx', path: '/tmp-dir/notes.docx' })).toEqual({
      file_id: '/tmp-dir/notes.docx', file_name: 'notes.docx', file_url: '/tmp-dir/notes.docx', directUrl: '/tmp-dir/notes.docx',
    });
  });
});
