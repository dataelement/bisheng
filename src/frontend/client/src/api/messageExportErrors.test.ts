import { normalizeApiError } from '@bisheng/api-client';
import request from './request';
import { exportMessagesApi, importMessagesToKnowledgeApi } from './messageExport';
jest.mock('./request', () => ({ __esModule: true, default: { postResponse: jest.fn(), post: jest.fn() } }));
it('propagates the original export error and its attachment evidence', async () => {
  const error = normalizeApiError({ status_code: 12064, data: { file_id: 4 } }, { message: 'export failed' });
  (request.postResponse as jest.Mock).mockRejectedValue(error);
  await expect(exportMessagesApi({ chatId: '1', messageIds: [1], format: 'docx' })).rejects.toBe(error);
});
it('does not convert an import failure into a successful result', async () => {
  const error = normalizeApiError({ status_code: 12065, data: { space_id: 4 } }, { message: 'import failed' });
  (request.post as jest.Mock).mockRejectedValue(error);
  await expect(importMessagesToKnowledgeApi({ chatId: '1', messageIds: [1], knowledgeSpaceId: 4, parentId: null })).rejects.toBe(error);
});
it('preserves the download body and filename headers', async () => {
  const blob = new Blob(['content'], { type: 'text/plain' });
  (request.postResponse as jest.Mock).mockResolvedValue({ data: blob, headers: { 'content-disposition': 'attachment; filename="report.txt"', 'content-type': 'text/plain' } });
  await expect(exportMessagesApi({ chatId: '1', messageIds: [1], format: 'txt' })).resolves.toEqual({ blob, filename: 'report.txt', mimeType: 'text/plain' });
});
