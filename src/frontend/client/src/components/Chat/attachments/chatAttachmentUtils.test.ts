import { getAttachmentUrl } from '~/api/chatApi';
import { getReissuableAttachment, reissueAttachmentUrl } from './chatAttachmentUtils';
import { collectChatAttachments, toChatArtifact } from './collectChatAttachments';

jest.mock('~/api/chatApi', () => ({ getAttachmentUrl: jest.fn() }));
jest.mock('~/pages/knowledge/FilePreview/previewUrlUtils', () => ({
    resolveKnowledgePreviewUrl: (url: string) => url.replace(/^https?:\/\/[^/]+/, ''),
}));

const mockGetAttachmentUrl = getAttachmentUrl as jest.Mock;

const kept = {
    file_id: 'g1',
    file_name: 'report.docx',
    object_name: 'chat/7/ab.docx',
    filepath: 'http://minio:9000/tmp-dir/ab.docx?sig',
};

beforeEach(() => mockGetAttachmentUrl.mockReset());

describe('re-issuing a kept attachment link', () => {
    it('asks the conversation for a fresh link when the file was kept', async () => {
        mockGetAttachmentUrl.mockResolvedValue('/bisheng/chat/7/ab.docx?fresh');

        const url = await reissueAttachmentUrl(getReissuableAttachment(kept, 'chat-1'), '/tmp-dir/ab.docx?sig');

        expect(mockGetAttachmentUrl).toHaveBeenCalledWith('chat-1', 'g1');
        expect(url).toBe('/bisheng/chat/7/ab.docx?fresh');
    });

    it('keeps the stored link for a file that was never kept', async () => {
        const unkept = { ...kept, object_name: undefined };

        const url = await reissueAttachmentUrl(getReissuableAttachment(unkept, 'chat-1'), '/tmp-dir/ab.docx?sig');

        expect(mockGetAttachmentUrl).not.toHaveBeenCalled();
        expect(url).toBe('/tmp-dir/ab.docx?sig');
    });

    it('falls back to the stored link when no fresh one can be issued', async () => {
        mockGetAttachmentUrl.mockResolvedValue(null);

        const url = await reissueAttachmentUrl(getReissuableAttachment(kept, 'chat-1'), '/tmp-dir/ab.docx?sig');

        expect(url).toBe('/tmp-dir/ab.docx?sig');
    });

    it('needs the conversation to issue a link', () => {
        expect(getReissuableAttachment(kept, undefined)).toBeUndefined();
    });
});

describe('workspace artifacts of kept attachments', () => {
    it('carry the attachment reference so the panel re-issues the link', () => {
        expect(toChatArtifact(kept, 'chat-1')).toEqual({
            file_id: 'g1',
            file_name: 'report.docx',
            file_url: '/tmp-dir/ab.docx?sig',
            directUrl: '/tmp-dir/ab.docx?sig',
            attachment: { conversationId: 'chat-1', fileId: 'g1' },
        });
    });

    it('take the conversation from the message they are collected from', () => {
        const [artifact] = collectChatAttachments([{ conversationId: 'chat-1', files: [kept] }]);

        expect(artifact.attachment).toEqual({ conversationId: 'chat-1', fileId: 'g1' });
    });
});
