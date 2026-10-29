import { act, render, waitFor } from '@testing-library/react';
import type { PDFDocumentProxy, PDFPageProxy } from 'pdfjs-dist';
import { toast } from '@bisheng/ui';
import { clearToasts, getToasts } from '../../../../../../packages/ui/src/components/Toast/toastStore';
import { PdfViewer } from './PdfViewer';

jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));

function createDocument(renderResult: () => Promise<void>, numPages = 1) {
    const page = {
        getViewport: ({ scale }: { scale: number }) => ({ width: 100 * scale, height: 200 * scale }),
        render: jest.fn(() => ({ promise: renderResult() })),
    } as unknown as PDFPageProxy;
    return { numPages, getPage: jest.fn(async () => page) } as unknown as PDFDocumentProxy;
}

const mount = (pdfDoc: PDFDocumentProxy, zoomLevel = 100) =>
    <PdfViewer pdfDoc={pdfDoc} zoomLevel={zoomLevel} targetPage={null} onCurrentPageChange={() => undefined} />;

beforeEach(() => {
    clearToasts();
    jest.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(600);
    global.IntersectionObserver = class {
        observe() {}
        unobserve() {}
        disconnect() {}
    } as unknown as typeof IntersectionObserver;
});
afterEach(() => { clearToasts(); });

it('reports page rendering failures once for a document, even when several pages fail', async () => {
    const notify = jest.spyOn(toast, 'error');
    const pdfDoc = createDocument(() => Promise.reject(new Error('Page decoding failed')), 3);
    render(mount(pdfDoc));
    await waitFor(() => expect(getToasts()).toEqual([
        expect.objectContaining({ type: 'error', message: 'com_knowledge.load_pdf_failed' }),
    ]));
    expect(notify).toHaveBeenCalledTimes(1);
});

it('reports a page retrieval failure', async () => {
    const pdfDoc = createDocument(() => Promise.resolve());
    jest.mocked(pdfDoc.getPage).mockRejectedValueOnce(new Error('Page unavailable'));
    render(mount(pdfDoc));
    await waitFor(() => expect(getToasts()).toHaveLength(1));
});

it('ignores rendering cancellation', async () => {
    const pdfDoc = createDocument(() => Promise.reject(Object.assign(new Error('Canceled'), { name: 'RenderingCancelledException' })));
    await act(async () => { render(mount(pdfDoc)); });
    expect(getToasts()).toEqual([]);
});

it('ignores a rendering failure after the viewer unmounts', async () => {
    let rejectRender!: (reason: unknown) => void;
    const pdfDoc = createDocument(() => new Promise((_resolve, reject) => { rejectRender = reject; }));
    const view = render(mount(pdfDoc));
    await waitFor(() => expect(rejectRender).toBeDefined());
    view.unmount();
    await act(async () => { rejectRender(new Error('Old render failed')); });
    expect(getToasts()).toEqual([]);
});

it('still reports a current document failure when zoom changes during rendering', async () => {
    let rejectRender!: (reason: unknown) => void;
    const pdfDoc = createDocument(() => new Promise((_resolve, reject) => { rejectRender = reject; }));
    const view = render(mount(pdfDoc));
    await waitFor(() => expect(rejectRender).toBeDefined());
    view.rerender(mount(pdfDoc, 150));
    await act(async () => { rejectRender(new Error('Current document failed')); });
    expect(getToasts()).toHaveLength(1);
});

it('ignores a previous document failure after switching documents', async () => {
    let rejectRender!: (reason: unknown) => void;
    const oldDocument = createDocument(() => new Promise((_resolve, reject) => { rejectRender = reject; }));
    const view = render(mount(oldDocument));
    await waitFor(() => expect(rejectRender).toBeDefined());
    view.rerender(mount(createDocument(() => Promise.resolve())));
    await act(async () => { rejectRender(new Error('Old document failed')); });
    expect(getToasts()).toEqual([]);
});

it('still renders again after a successful render and a zoom change', async () => {
    const pdfDoc = createDocument(() => Promise.resolve());
    const view = render(mount(pdfDoc));
    await waitFor(() => expect(pdfDoc.getPage).toHaveBeenCalledTimes(1));
    await act(async () => { view.rerender(mount(pdfDoc, 150)); });
    expect(pdfDoc.getPage).toHaveBeenCalledTimes(2);
    expect(getToasts()).toEqual([]);
});
