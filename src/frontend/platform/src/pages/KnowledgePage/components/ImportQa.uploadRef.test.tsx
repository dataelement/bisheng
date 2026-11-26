import { createRef, type ReactNode } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { ImportQa } from './ImportQa';

const api = vi.hoisted(() => ({ preview: vi.fn(), importFile: vi.fn(), upload: { ref: 'issued-ref-D' as string | undefined } }));
vi.mock('@/controllers/API', () => ({ getQaFile: vi.fn(), getQaFilePreview: api.preview, postImportQaFile: api.importFile }));
vi.mock('@/controllers/request', () => ({ handleUiRequest: (callback: (...args: unknown[]) => unknown) => callback }));
vi.mock('react-router-dom', () => ({ useParams: () => ({ id: 'kb-1' }) }));
vi.mock('@/components/bs-comp/FileView', () => ({ checkSassUrl: (value: string) => value }));
vi.mock('@/util/utils', () => ({ downloadFile: vi.fn() }));
vi.mock('@/utils', () => ({ generateUUID: () => 'row-1' }));
vi.mock('@/components/bs-ui/upload/simple', () => ({ default: ({ onSuccess }: { onSuccess: (...args: unknown[]) => unknown }) =>
    <button onClick={() => void onSuccess('qa.xlsx', 'tmp/qa.xlsx', api.upload.ref)}>synthetic-upload</button> }));
vi.mock('@bisheng/ui', () => ({ Button: ({ children, loading: _loading, ...props }: { children: ReactNode; loading?: boolean }) => { void _loading; return <button {...props}>{children}</button>; }, toast: { show: vi.fn() } }));
vi.mock('@/components/bs-ui/dialog', () => ({
    Dialog: ({ open, children }: { open: boolean; children: ReactNode }) => open ? <div>{children}</div> : null,
    DialogClose: 'div', DialogContent: 'div', DialogFooter: 'div', DialogHeader: 'div', DialogTitle: 'div',
}));
vi.mock('@/components/bs-ui/table', () => ({ Table: 'div', TableBody: 'div', TableCell: 'div', TableHead: 'div', TableRow: 'div' }));
afterEach(() => { cleanup(); vi.clearAllMocks(); api.upload.ref = 'issued-ref-D'; });

it('retains the upload-issued reference from preview through submit', async () => {
    api.preview.mockResolvedValue({ result: [{ questions: ['question'], answers: '["answer"]' }] });
    api.importFile.mockResolvedValue({ errors: [[]] });
    const ref = createRef<{ open: () => void }>();
    render(<ImportQa ref={ref} knowlageId="kb-1" onChange={vi.fn()} />);
    act(() => ref.current!.open());
    fireEvent.click(screen.getByText('synthetic-upload'));
    await waitFor(() => expect(screen.getAllByText('answer')).toHaveLength(2));
    expect(api.preview).toHaveBeenCalledWith('kb-1', { size: 10, url: 'tmp/qa.xlsx', preview_upload_ref: 'issued-ref-D' });
    fireEvent.click(screen.getByText('submit'));
    await waitFor(() => expect(api.importFile).toHaveBeenCalledWith('kb-1', { url: 'tmp/qa.xlsx', preview_upload_ref: 'issued-ref-D' }));
    act(() => ref.current!.open());
    expect(screen.queryAllByText('answer')).toHaveLength(0);
    fireEvent.click(screen.getByText('submit'));
    expect(api.importFile).toHaveBeenCalledTimes(1);
});

it('clears stale preview and never invents a missing upload reference', async () => {
    api.preview.mockResolvedValue({ result: [{ questions: ['question'], answers: '["answer"]' }] });
    const ref = createRef<{ open: () => void }>();
    render(<ImportQa ref={ref} knowlageId="kb-1" onChange={vi.fn()} />);
    act(() => ref.current!.open());
    fireEvent.click(screen.getByText('synthetic-upload'));
    await waitFor(() => expect(screen.getAllByText('answer')).toHaveLength(2));
    api.upload.ref = undefined;
    fireEvent.click(screen.getByText('synthetic-upload'));
    await waitFor(() => expect(screen.queryAllByText('answer')).toHaveLength(0));
    expect(api.preview).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('submit'));
    expect(api.importFile).not.toHaveBeenCalled();
});
