import { render, cleanup, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import FilePreviewPage from '~/pages/knowledge/FilePreview/FilePreviewPage';
const api = vi.hoisted(() => ({ preview: vi.fn() }));
vi.mock('~/api/knowledge', () => ({ getFilePreviewApi: api.preview, getFileDownloadApi: vi.fn() }));
vi.mock('~/api/permission', () => ({ getMyResourcePermissions: async () => ({ actions: [] }) }));
vi.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useAuthContext: () => ({ user: null }) }));
vi.mock('~/pages/Subscription/AiChat/FileAiDock', () => ({ FileAiDock: () => null }));
vi.mock('~/pages/knowledge/FilePreview/RichKnowledgePreview', () => ({ RichKnowledgePreview: () => null }));
vi.mock('~/pages/knowledge/FilePreview/index', () => ({ default: ({ fileUrl, fileType }: { fileUrl: string; fileType: string }) => <output data-type={fileType}>{fileUrl}</output> }));
const handle = '/api/v1/knowledge/space/9/files/3/content/preview?version_id=7&generation=1&epoch=3';
function open(url: string) {
  api.preview.mockResolvedValue({ media_kind: 'text_excerpt', original_url: '/bisheng/original/report.docx', preview_url: url });
  render(<MemoryRouter initialEntries={['/knowledge/file/3?spaceId=9&name=report.docx']}><Routes><Route path="/knowledge/file/:fileId" element={<FilePreviewPage />} /></Routes></MemoryRouter>);
}
beforeEach(() => { vi.stubGlobal('__APP_ENV__', { BASE_URL: '/workspace' }); vi.stubGlobal('matchMedia', () => ({ matches: false, addEventListener() {}, removeEventListener() {} })); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it('opens the authorized excerpt handle as plain text, not the original document or a PDF', async () => {
  open(handle); expect((await screen.findByText(`/workspace${handle}`)).getAttribute('data-type')).toBe('txt');
});
it.each(['', 'https://private.example/preview', handle.replace('/3/content/', '/4/content/')])('refuses absent or unrelated excerpt %s rather than opening original bytes', async url => {
  open(url); expect(await screen.findByText('com_knowledge.fetch_preview_link_failed')).toBeTruthy();
});
