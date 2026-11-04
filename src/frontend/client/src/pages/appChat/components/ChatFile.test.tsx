import { fireEvent, render, screen } from '@testing-library/react';
import { createServer, get, type Server } from 'node:http';
import { downloadFile } from '~/utils';
import { normalizeHistory } from '@bisheng/chat/core';
import { ClientMessageAttachments } from './ClientMessageAttachments';

function AppChatFileList({ files }: { files: Record<string, unknown>[] }) {
    const [message] = normalizeHistory([{ category: 'answer', files }], { mode: 'assistant', sessionKey: 'test' });
    return <ClientMessageAttachments message={message} conversationId="test" />;
}

jest.mock('@bisheng/chat', () => ({ ConversationAttachments: jest.requireActual('../../../../../packages/chat/src/components/ConversationAttachments').ConversationAttachments }));
jest.mock('~/utils', () => ({ downloadFile: jest.fn(), cn: (...parts: string[]) => parts.filter(Boolean).join(' ') }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/api/chatApi', () => ({ getAttachmentUrl: jest.fn() }));
jest.mock('~/components/ui', () => ({ OGDialog: () => null, OGDialogContent: () => null }));
jest.mock('~/components/Chat/attachments/MediaAttachmentChip', () => ({ MediaAttachmentChip: () => null }));

const filename = 'APP_FILE_120.pdf';
const signature = '?X-Amz-Credential=test%2Fdate%2Fs3&X-Amz-Signature=abc%2B123';
const objectPath = '/bisheng/chat/7/APP_FILE_120.pdf';

beforeEach(() => {
    __APP_ENV__.BASE_URL = '/workspace';
    jest.mocked(downloadFile).mockReset();
});

describe('application history attachment downloads', () => {
    it.each(['file_url', 'filepath', 'file_path', 'path', 'url'])('resolves a stored %s to the bucket root', (field) => {
        render(<AppChatFileList files={[{ file_name: filename, [field]: `http://storage.internal:9000${objectPath}${signature}` }]} />);
        fireEvent.click(screen.getByText(filename));
        expect(downloadFile).toHaveBeenCalledWith(`${objectPath}${signature}`, filename);
    });

    it.each([
        objectPath,
        objectPath.slice(1),
        `/workspace${objectPath}`,
        `/workspace/workspace${objectPath}`,
        `//storage.internal:9000${objectPath}`,
    ])('normalizes the historical path %s while preserving its signature', (path) => {
        render(<AppChatFileList files={[{ name: filename, file_url: path + signature }]} />);
        fireEvent.click(screen.getByText(filename));
        expect(downloadFile).toHaveBeenCalledWith(`${objectPath}${signature}`, filename);
    });

    it('uses the temporary bucket proxy for a newly uploaded document', () => {
        render(<AppChatFileList files={[{ name: filename, filepath: `https://storage.internal/tmp-dir/upload.pdf${signature}` }]} />);
        fireEvent.click(screen.getByText(filename));
        expect(downloadFile).toHaveBeenCalledWith(`/tmp-dir/upload.pdf${signature}`, filename);
    });

    it('preserves encoded object names and the original download filename', () => {
        const name = decodeURIComponent('%E5%8E%86%E5%8F%B2%E6%8A%A5%E5%91%8A%202026.pdf');
        const path = '/bisheng/chat/7/%E5%8E%86%E5%8F%B2%20a%2Fb.pdf';
        render(<AppChatFileList files={[{ name, file_url: `https://storage.internal${path}${signature}` }]} />);
        fireEvent.click(screen.getByText(name));
        expect(downloadFile).toHaveBeenCalledWith(path + signature, name);
    });

    it.each([
        'https://documents.example.org/report.pdf?download=1',
        '/api/v1/files/7/content',
        'blob:http://localhost:3080/test',
    ])('preserves a resource with its own URL: %s', (path) => {
        render(<AppChatFileList files={[{ filename, file_url: path }]} />);
        fireEvent.click(screen.getByText(filename));
        expect(downloadFile).toHaveBeenCalledWith(path, filename);
    });

    it('keeps an attachment without a URL from starting a download', () => {
        render(<AppChatFileList files={[{ name: filename }]} />);
        fireEvent.click(screen.getByText(filename));
        expect(downloadFile).not.toHaveBeenCalled();
    });
});

describe('download routing with a frontend catch-all', () => {
    let server: Server;
    let origin: string;
    const requests: string[] = [];
    const pdf = Buffer.from('%PDF-1.4\n% synthetic attachment response\n%%EOF\n');

    beforeAll(async () => {
        server = createServer((request, response) => {
            requests.push(request.url || '');
            if (request.url === objectPath + signature) {
                response.writeHead(200, { 'content-type': 'application/pdf' });
                response.end(pdf);
                return;
            }
            response.writeHead(200, { 'content-type': 'text/html' });
            response.end('<!doctype html><html><body><div id="root"></div></body></html>');
        });
        await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve));
        const address = server.address();
        if (!address || typeof address === 'string') throw new Error('Fixture address unavailable');
        origin = `http://127.0.0.1:${address.port}`;
    });

    afterAll(async () => {
        await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()));
    });

    it('requests PDF bytes when the user clicks a valid historical attachment', async () => {
        let received: Promise<{ contentType: string | undefined; body: Buffer }> | undefined;
        jest.mocked(downloadFile).mockImplementation((url: string) => {
            received = new Promise((resolve, reject) => {
                get(new URL(url, origin), response => {
                    const chunks: Buffer[] = [];
                    response.on('data', chunk => chunks.push(Buffer.from(chunk)));
                    response.on('end', () => resolve({ contentType: response.headers['content-type'], body: Buffer.concat(chunks) }));
                    response.on('error', reject);
                }).on('error', reject);
            });
            return Promise.resolve();
        });
        render(<AppChatFileList files={[{ file_name: filename, file_url: `http://storage.internal:9000${objectPath}${signature}` }]} />);
        fireEvent.click(screen.getByText(filename));
        const result = await received;
        expect(result?.contentType).toBe('application/pdf');
        expect(result?.body).toEqual(pdf);
        expect(requests).toEqual([objectPath + signature]);
    });
});
