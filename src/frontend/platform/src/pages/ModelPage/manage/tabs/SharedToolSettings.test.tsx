import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { beforeEach, expect, it, vi } from 'vitest';
import { SharedToolSettings } from './SharedToolSettings';

const mocks = vi.hoisted(() => ({
    get: vi.fn(), save: vi.fn(), error: vi.fn(), success: vi.fn(),
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
vi.mock('@/controllers/request', () => ({ showApiError: mocks.error }));
vi.mock('@bisheng/ui', async (importOriginal) => ({
    ...await importOriginal<typeof import('@bisheng/ui')>(),
    toast: { show: mocks.success },
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
});

it('does not load or expose shared configuration to non-super admins', () => {
    mocks.user.is_global_super = false;
    render(<SharedToolSettings />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(mocks.get).not.toHaveBeenCalled();
});

it('saves search settings through the platform tool id and retains the masked key', async () => {
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.searchTool' }));
    const input = await screen.findByLabelText(/Bing Search URL/);
    expect(input).toHaveValue('https://search.example.test');
    fireEvent.change(input, { target: { value: 'https://updated.example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'build.confirm' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(16, expect.objectContaining({
        type: 'bing', config: expect.objectContaining({ bing: { api_key: '******', base_url: 'https://updated.example.test' } }),
    })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    expect(mocks.get).toHaveBeenCalledWith('default', { action: 'visible' });
});

it('saves drawing settings separately and reads fresh settings when reopened', async () => {
    render(<SharedToolSettings />);
    const button = screen.getByRole('button', { name: 'model.configureTool model.drawingTool' });
    fireEvent.click(button);
    fireEvent.change(await screen.findByLabelText('OpenAI Base URL'), { target: { value: 'https://new.example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }));
    await waitFor(() => expect(mocks.save).toHaveBeenCalledWith(4, expect.objectContaining({ openai_api_base: 'https://new.example.test' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    mocks.get.mockResolvedValue([search, { ...drawing, extra: JSON.stringify({ openai_api_key: '******', openai_api_base: 'https://external-update.example.test' }) }]);
    fireEvent.click(button);
    expect(await screen.findByLabelText('OpenAI Base URL')).toHaveValue('https://external-update.example.test');
});

it('retains input and reports a failed save without claiming success', async () => {
    const error = new Error('save failed');
    mocks.save.mockRejectedValue(error);
    render(<SharedToolSettings />);
    fireEvent.click(screen.getByRole('button', { name: 'model.configureTool model.drawingTool' }));
    const input = await screen.findByLabelText('OpenAI Base URL');
    fireEvent.change(input, { target: { value: 'https://draft.example.test' } });
    fireEvent.click(screen.getByRole('button', { name: 'confirm' }));
    await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
    expect(input).toHaveValue('https://draft.example.test');
    expect(mocks.success).not.toHaveBeenCalled();
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
    await screen.findByLabelText('OpenAI Base URL');
    const confirm = screen.getByRole('button', { name: 'confirm' });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(confirm).toBeDisabled();
    expect(mocks.save).toHaveBeenCalledTimes(1);
    finish(true);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
});
