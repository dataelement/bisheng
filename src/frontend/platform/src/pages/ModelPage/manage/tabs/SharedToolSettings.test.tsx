import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import { SharedToolSettings } from './SharedToolSettings';

const mocks = vi.hoisted(() => ({
    get: vi.fn(), save: vi.fn(), getSearch: vi.fn(), saveSearch: vi.fn(), error: vi.fn(), success: vi.fn(), notice: vi.fn(),
    user: { is_global_super: true },
}));
vi.mock('@/contexts/userContext', async () => {
    const { createContext } = await import('react');
    return { userContext: createContext({ user: mocks.user }) };
});
vi.mock('react-i18next', () => ({ useTranslation: () => ({
    t: (key: string, options?: { tool?: string }) => options?.tool ? `${key} ${options.tool}` : key,
}) }));
vi.mock('@/controllers/API/tools', () => ({ getToolsApi: mocks.get, updateToolApi: mocks.save }));
vi.mock('@/controllers/API/webSearch', () => ({
    getWebSearchSettings: mocks.getSearch, putWebSearchSettings: mocks.saveSearch,
    parseWebSearchSchema: vi.fn(), testWebSearch: vi.fn(),
}));
vi.mock('@/controllers/request', () => ({ showApiError: mocks.error }));
vi.mock('@bisheng/ui', async (importOriginal) => ({
    ...await importOriginal<typeof import('@bisheng/ui')>(),
    toast: { show: mocks.success },
    notification: { open: mocks.notice },
}));

const search = {
    id: 16, name: 'Renamed search', children: [{ tool_key: 'web_search' }],
    extra: JSON.stringify({ type: 'bing', config: { bing: { api_key: '******', base_url: 'https://search.example.test' } } }),
};
const drawing = {
    id: 4, name: 'Renamed drawing', children: [{ tool_key: 'dalle_image_generator' }],
    extra: JSON.stringify({ openai_api_key: '******', openai_api_base: 'https://images.example.test' }),
};

beforeEach(() => {
    vi.clearAllMocks();
    mocks.user.is_global_super = true;
    mocks.get.mockResolvedValue([search, drawing]);
    mocks.save.mockResolvedValue(true);
    mocks.getSearch.mockResolvedValue({
        revision: 'revision-1', enabled: true, type: 'bing', prompt: '', custom_secret_configured: false,
        providers: { bing: { api_key: '******', base_url: 'https://search.example.test' } },
    });
    mocks.saveSearch.mockResolvedValue({ revision: 'revision-2' });
});

it('does not load or expose shared configuration to non-super admins', () => {
    mocks.user.is_global_super = false;
    render(<SharedToolSettings />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
    expect(mocks.getSearch).not.toHaveBeenCalled();
});

it('saves search settings through the platform tool id and retains the masked key', async () => {
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.searchTool' }));
    const input = await screen.findByLabelText(/Bing Search URL/);
    expect(input).toHaveValue('https://search.example.test');
    fireEvent.change(input, { target: { value: 'https://updated.example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'build.confirm' }));
    await waitFor(() => expect(mocks.saveSearch).toHaveBeenCalledWith('16', expect.objectContaining({
        revision: 'revision-1', custom_secret: { action: 'keep' },
        type: 'bing', providers: expect.objectContaining({ bing: { api_key: '******', base_url: 'https://updated.example.test' } }),
    })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mocks.get).toHaveBeenCalledWith('default', { action: 'visible' });
    expect(mocks.getSearch).toHaveBeenCalledWith('16');
    expect(mocks.save).not.toHaveBeenCalled();
});

it('retains the search draft and unlocks the dialog when the revision save fails', async () => {
    mocks.saveSearch.mockRejectedValue(new Error('conflicting revision'));
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.searchTool' }));
    const input = await screen.findByLabelText(/Bing Search URL/);
    fireEvent.change(input, { target: { value: 'https://draft-search.example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'build.confirm' }));
    await waitFor(() => expect(mocks.notice).toHaveBeenCalledWith(expect.objectContaining({ type: 'error' })));
    expect(input).toHaveValue('https://draft-search.example.test');
    expect(screen.getByRole('button', { name: 'build.confirm' })).toBeEnabled();
    expect(mocks.notice).not.toHaveBeenCalledWith(expect.objectContaining({ type: 'success' }));
});

it('locks search submission and prevents closing while its settings request is pending', async () => {
    let finish!: (value: { revision: string }) => void;
    mocks.saveSearch.mockReturnValue(new Promise<{ revision: string }>((resolve) => { finish = resolve; }));
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.searchTool' }));
    await screen.findByLabelText(/Bing Search URL/);
    const confirm = screen.getByRole('button', { name: 'build.confirm' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(confirm).toBeDisabled();
    expect(mocks.saveSearch).toHaveBeenCalledTimes(1);
    finish({ revision: 'revision-2' });
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});

it('saves drawing settings separately and reads fresh settings when reopened', async () => {
    render(<SharedToolSettings />);
    const button = screen.getByRole('button', { name: 'model.configureTool model.drawingTool' });
    fireEvent.click(button);
    fireEvent.change(await screen.findByLabelText(/imageGeneration.openai_api_base/), { target: { value: 'https://images.example.test/v2' } });
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(4, expect.objectContaining({ openai_api_base: 'https://images.example.test/v2' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    mocks.get.mockResolvedValue([search, { ...drawing, extra: JSON.stringify({ openai_api_key: '******', openai_api_base: 'https://external-update.example.test' }) }]);
    fireEvent.click(button);
    expect(await screen.findByLabelText(/imageGeneration.openai_api_base/)).toHaveValue('https://external-update.example.test');
});

it('retains input and reports a failed save without claiming success', async () => {
    const error = new Error('save failed');
    mocks.save.mockRejectedValue(error);
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.drawingTool' }));
    const input = await screen.findByLabelText(/imageGeneration.openai_api_base/);
    fireEvent.change(input, { target: { value: 'https://images.example.test/draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
    expect(input).toHaveValue('https://images.example.test/draft');
    expect(mocks.success).not.toHaveBeenCalled();
});

it('opens the unified image tool and saves the selected model with the platform settings', async () => {
    mocks.get.mockResolvedValue([search, { ...drawing, children: [{ tool_key: 'image_generation' }] }]);
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.drawingTool' }));
    fireEvent.change(await screen.findByLabelText(/imageGeneration.model/), { target: { value: 'image-model-next' } });
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(4, expect.objectContaining({
        model: 'image-model-next', openai_api_key: '******', provider: 'openai',
    })));
});

it.each([[], [search, search], [{ ...search, extra: 'null' }], [{ ...search, extra: '{broken' }]])(
    'rejects missing, ambiguous or invalid tool configuration (%j)', async (...tools) => {
        mocks.get.mockResolvedValue(tools);
        render(<SharedToolSettings />);
        fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.searchTool' }));
        await waitFor(() => expect(mocks.error).toHaveBeenCalled());
        expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
        expect(mocks.save).not.toHaveBeenCalled();
    },
);

it('locks the form and blocks repeated saves while the request is pending', async () => {
    let finish!: (value: boolean) => void;
    mocks.save.mockReturnValue(new Promise<boolean>((resolve) => { finish = resolve; }));
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.drawingTool' }));
    await screen.findByLabelText(/imageGeneration.openai_api_base/);
    const confirm = screen.getByRole('button', { name: 'confirm' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();
    expect(mocks.save).toHaveBeenCalledTimes(1);
    finish(true);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
