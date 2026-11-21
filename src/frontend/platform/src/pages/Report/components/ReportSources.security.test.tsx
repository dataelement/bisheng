import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import Report from '../index';
import ReportWordEdit from '@/pages/BuildPage/flow/FlowNode/component/ReportWordEdit';

const mocks = vi.hoisted(() => ({ upload: vi.fn() }));
vi.mock('@/controllers/API/flow', () => ({ getReportFormApi: () => Promise.resolve({ version_key: 'server-key', temp_url: '' }) }));
vi.mock('@/controllers/API/workflow', () => ({ getWorkflowReportTemplate: () => Promise.resolve({ version_key: 'server-key', url: '' }), saveWorkflowReportTemplate: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@/modals/UploadModal/upload', () => ({ uploadFileWithProgress: mocks.upload }));
vi.mock('react-router-dom', () => ({ useParams: () => ({ id: 'workflow-1' }), useNavigate: () => vi.fn() }));
vi.mock('@bisheng/ui', () => ({ Button: 'button', toast: { show: vi.fn() } }));
vi.mock('@/components/bs-ui/dialog', () => ({ DialogClose: 'div' }));
vi.mock('./Label', () => ({ default: () => null }));
vi.mock('@/pages/BuildPage/flow/FlowNode/component/SelectVar', () => ({ default: () => null }));
vi.mock('./Word', () => ({ default: ({ data }: { data: unknown }) => <output data-testid="word-data">{JSON.stringify(data)}</output> }));
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks(); });

function renderSurface(workflow: boolean) {
    return render(workflow ? <ReportWordEdit versionKey="" nodeId="node-1" onChange={vi.fn()} /> : <Report />);
}

it.each([false, true])('new report selects builtin source without a browser asset URL (workflow=%s)', async workflow => {
    renderSurface(workflow);
    fireEvent.click(await screen.findByText('report.newButton'));
    await waitFor(() => expect(JSON.parse(screen.getByTestId('word-data').textContent!)).toEqual({ key: 'server-key', path: '', source_kind: 'empty' }));
});

it.each([false, true])('import retains the exact issued upload source reference (workflow=%s)', async workflow => {
    mocks.upload.mockResolvedValue({ file_path: '/bucket/tmp/import.docx', preview_upload_ref: 'issued-source-ref' });
    const click = vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(function (this: HTMLInputElement) {
        fireEvent.change(this, { target: { files: [new File(['synthetic'], 'template.docx')] } });
    });
    renderSurface(workflow);
    fireEvent.click(await screen.findByText('report.importButton'));
    await waitFor(() => expect(JSON.parse(screen.getByTestId('word-data').textContent!)).toEqual({ key: 'server-key', path: '/bucket/tmp/import.docx', preview_upload_ref: 'issued-source-ref' }));
    expect(click).toHaveBeenCalledTimes(1);
});

it.each([false, true])('refuses imports with no issued upload reference (workflow=%s)', async workflow => {
    mocks.upload.mockResolvedValue({ file_path: '/bucket/tmp/import.docx' });
    vi.spyOn(HTMLInputElement.prototype, 'click').mockImplementation(function (this: HTMLInputElement) {
        fireEvent.change(this, { target: { files: [new File(['synthetic'], 'template.docx')] } });
    });
    renderSurface(workflow);
    fireEvent.click(await screen.findByText('report.importButton'));
    await waitFor(() => expect(mocks.upload).toHaveBeenCalledTimes(1));
    expect(screen.queryByTestId('word-data')).toBeNull();
});
