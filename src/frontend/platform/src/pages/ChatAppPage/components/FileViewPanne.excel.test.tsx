import { Suspense } from 'react';
import { cleanup, render, waitFor } from '@testing-library/react';
import { createInstance } from 'i18next';
import { I18nextProvider } from 'react-i18next';
import { afterEach, expect, it, vi } from 'vitest';
import request from '@/controllers/request';
import { getSourceChunksApi } from '@/controllers/API';
import knowledge from '../../../../public/locales/en-US/knowledge.json';
import FileViewPanne from './FileViewPanne';

vi.unmock('react-i18next');
vi.mock('@/controllers/request', () => ({ default: { post: vi.fn() } }));
vi.mock('@bisheng/file-viewers', () => ({ ExcelPreview: ({ filePath }: { filePath: string }) => <output data-testid="excel">{filePath}</output> }));
vi.mock('@/components/bs-comp/FileView', () => ({ default: () => <output data-testid="pdf" /> }));
vi.mock('@/components/bs-ui/utils', () => ({ generateUUID: () => 'label' }));
vi.mock('@/pages/KnowledgePage/components/DocxFileViewer', () => ({ default: () => <output data-testid="docx" /> }));
vi.mock('@/pages/KnowledgePage/components/TxtFileViewer', () => ({ default: () => null }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const rawChunk = (fileId: number, extension: string, score: number, preview = '') => ({
    file_id: fileId, source: `folder/file.${extension}`, parse_type: 'un_etl4lm', right: true,
    original_url: `/object/bisheng/original/${fileId}.${extension}?signature=test`,
    preview_url: preview, chunk_bboxes: '', score,
});

async function openFile(file: unknown) {
    const i18n = createInstance();
    await i18n.init({ lng: 'en', defaultNS: 'bs', resources: { en: { bs: {}, knowledge } } });
    return render(<I18nextProvider i18n={i18n}><FileViewPanne file={file} /></I18nextProvider>);
}

it('opens the highest-scoring Excel from the supplied recall response using its preview URL', async () => {
    const preview = '/object/bisheng/preview/98273.xlsx?signature=test';
    vi.mocked(request.post).mockResolvedValueOnce([
        rawChunk(97553, 'docx', 0.23), rawChunk(98273, 'xlsx', 0.43, preview),
        rawChunk(98277, 'md', 0.32),
    ]);
    const files = await getSourceChunksApi('0d148133dc056be26bfea3172d12a583', 443408, 'test;file');
    expect(request.post).toHaveBeenCalledWith('/api/v1/qa/chunk', expect.objectContaining({ message_id: 443408 }));
    expect(files[0]).toMatchObject({ id: 98273, score: 0.43, suffix: 'xlsx' });
    const view = await openFile(files[0]);
    expect(view.getByTestId('excel').textContent).toBe(preview);
    expect(view.queryByTestId('docx')).toBeNull();
    expect(view.queryByText('fileNotSupported')).toBeNull();
});

it.each(['xls', 'xlsx'])('falls back to the original %s when no preview URL exists', async extension => {
    const chunk = rawChunk(98273, extension, 0.43);
    vi.mocked(request.post).mockResolvedValueOnce([chunk]);
    const [file] = await getSourceChunksApi('chat', 443408, 'file');
    const view = await openFile(file);
    expect(view.getByTestId('excel').textContent).toBe(chunk.original_url);
});

it('loads the knowledge namespace when opened directly from audit and localizes unsupported formats', async () => {
    const read = vi.fn((language: string, namespace: string, callback: (error: null, data: object) => void) => {
        callback(null, namespace === 'knowledge' ? knowledge : {});
    });
    const i18n = createInstance();
    await i18n.use({ type: 'backend', read }).init({ lng: 'en', fallbackLng: false, ns: ['bs'], defaultNS: 'bs' });
    expect(i18n.hasResourceBundle('en', 'knowledge')).toBe(false);
    const file = { fileName: 'unsupported.zip', fileUrl: '/file.zip', parse_type: 'un_etl4lm', chunks: [{ score: 1, box: '' }] };
    const view = render(<I18nextProvider i18n={i18n}><Suspense fallback={<div>Loading</div>}><FileViewPanne file={file} /></Suspense></I18nextProvider>);
    await waitFor(() => expect(view.getByText(knowledge.fileNotSupported)).toBeVisible());
    expect(read).toHaveBeenCalledWith('en', 'knowledge', expect.any(Function));
    expect(view.queryByText('fileNotSupported')).toBeNull();
});
