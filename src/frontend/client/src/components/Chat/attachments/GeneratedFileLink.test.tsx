import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { getAttachmentUrl } from '~/api/chatApi';
import { downloadFile } from '~/utils';
import { isWorkspaceRelativeHref, matchGeneratedFile, renderGeneratedFileLink } from './GeneratedFileLink';

jest.mock('~/api/chatApi', () => ({ getAttachmentUrl: jest.fn() }));
jest.mock('~/utils', () => ({ downloadFile: jest.fn() }));
jest.mock('~/pages/knowledge/FilePreview/previewUrlUtils', () => ({ resolveKnowledgePreviewUrl: (url: string) => url }));

// A CJK file name, as the model writes them; the encoded form is what a link carries.
const ENCODED_NAME = '%E5%8C%97%E4%BA%AC%E4%BB%8A%E6%97%A5%E5%A4%A9%E6%B0%94.docx';
const NAME = decodeURIComponent(ENCODED_NAME);

const report = {
    file_id: 'g1',
    file_name: NAME,
    path: `output/${NAME}`,
    object_name: 'chat/7/ab.docx',
    filepath: '/tmp-dir/ab.docx?sig',
};

describe('matching answer links to generated files', () => {
    it.each([
        [`output/${NAME}`],
        [`output/${ENCODED_NAME}`],
        [`./output/${NAME}`],
        [`/output/${NAME}`],
    ])('matches %s', (href) => {
        expect(matchGeneratedFile([report], href)).toBe(report);
    });

    it('never matches an absolute link', () => {
        expect(matchGeneratedFile([report], `https://example.com/output/${NAME}`)).toBeUndefined();
    });

    it('tolerates a malformed escape', () => {
        expect(matchGeneratedFile([report], 'output/%E5%.docx')).toBeUndefined();
        expect(isWorkspaceRelativeHref('output/%E5%.docx')).toBe(true);
    });
});

describe('rendering answer links', () => {
    const renderLink = (href: string, files = [report]) =>
        renderGeneratedFileLink(files, href, 'the report', { conversationId: 'chat-1' });

    it('opens a matched file through a fresh link', async () => {
        (getAttachmentUrl as jest.Mock).mockResolvedValue('/bisheng/chat/7/ab.docx?fresh');
        render(<>{renderLink(`output/${NAME}`)}</>);

        fireEvent.click(screen.getByRole('button', { name: 'the report' }));

        await waitFor(() =>
            expect(downloadFile).toHaveBeenCalledWith('/bisheng/chat/7/ab.docx?fresh', NAME),
        );
    });

    it.each(['output/missing.docx', 'scratch/tmp.csv'])('shows an unmatched working-directory link %s as text', (href) => {
        const { container } = render(<>{renderLink(href, [])}</>);

        expect(container.querySelector('a')).toBeNull();
        expect(screen.queryByRole('button')).toBeNull();
        expect(container.textContent).toBe('the report');
    });

    it('leaves other links to the default renderer', () => {
        expect(renderLink('https://example.com/a.docx')).toBeUndefined();
        expect(renderLink('docs/a.docx')).toBeUndefined();
    });
});
