import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createRef, type ComponentRef } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import CreateApp from '@/pages/BuildPage/CreateApp';
import { AppType } from '@/types/app';

const api = vi.hoisted(() => ({ list: vi.fn(), create: vi.fn(), save: vi.fn(), navigate: vi.fn(), error: vi.fn() }));
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: { isPro: false } }) }));
vi.mock('@/controllers/API', () => ({ readTempsDatabase: api.list }));
vi.mock('@/controllers/API/assistant', () => ({ createAssistantsApi: api.create, saveAssistanttApi: api.save }));
vi.mock('@/controllers/API/workflow', () => ({ copyReportTemplate: vi.fn(), createWorkflowApi: vi.fn() }));
vi.mock('@/controllers/API/finetune', () => ({ getAssistantModelConfig: vi.fn(), getLlmDefaultModel: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: api.error }));
vi.mock('react-router-dom', () => ({ useNavigate: () => api.navigate }));
vi.mock('@/components/Pro/security/AssistantSetting', () => ({ default: () => null }));
vi.mock('@/components/bs-comp/cardComponent/avatar', () => ({ default: () => null }));
vi.mock('@/components/bs-ui/input/avator', () => ({ default: () => null }));
vi.mock('@/modals/UploadModal/upload', () => ({ uploadFileWithProgress: vi.fn() }));
vi.mock('@/components/bs-ui/utils', async (original) => ({
    ...await original<typeof import('@/components/bs-ui/utils')>(), generateUUID: () => 'fixed',
}));

beforeEach(() => {
    vi.clearAllMocks();
    api.create.mockResolvedValue({ id: 'created', model_name: 'default' });
    api.save.mockResolvedValue({});
});
afterEach(cleanup);

function renderModal() {
    const ref = createRef<ComponentRef<typeof CreateApp>>();
    render(<CreateApp ref={ref} />);
    act(() => { ref.current!.open(AppType.ASSISTANT, 205); });
}

it('loads the assistant type and creates an assistant from its template configuration', async () => {
    api.list.mockResolvedValue([{ id: 205, name: 'Template', description: 'Description', data: { prompt: 'Instructions' } }]);
    renderModal();
    await screen.findByDisplayValue('Template-fixed');
    expect(api.list).toHaveBeenCalledWith(AppType.ASSISTANT, 205);
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    await waitFor(() => expect(api.navigate).toHaveBeenCalledWith('/assistant/created'));
    expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ id: 'created', prompt: 'Instructions' }));
});

it('cannot create a blank application while its selected template is still loading', async () => {
    api.list.mockImplementationOnce(() => new Promise(() => {}));
    renderModal();
    fireEvent.change(screen.getByRole('textbox', { name: /build_assistantName/ }), { target: { value: 'Typed name' } });
    fireEvent.click(screen.getByRole('button', { name: 'create' }));
    expect(api.create).not.toHaveBeenCalled();
});

it('discards an outstanding template detail response after switching tenants', async () => {
    let resolve!: (value: unknown) => void;
    api.list.mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    renderModal();
    act(() => { window.dispatchEvent(new Event('bisheng:management-scope-changed')); });
    await act(async () => { resolve([{ id: 205, name: 'Old tenant', data: { prompt: 'Old' } }]); });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue('Old tenant-fixed')).not.toBeInTheDocument();
    expect(api.create).not.toHaveBeenCalled();
});
