import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import McpServerEditorDialog from './EditMcp';

const mocks = vi.hoisted(() => ({ parse: vi.fn(), create: vi.fn(), error: vi.fn() }));
vi.mock('@/controllers/API/tools', () => ({
    getMcpServeByConfig: mocks.parse, createTool: mocks.create, updateTool: mocks.create,
    deleteTool: vi.fn(), testMcpApi: vi.fn(),
}));
vi.mock('@/controllers/request', () => ({ showApiError: mocks.error, handleUiRequest: (fn: () => Promise<unknown>) => () => fn().catch(mocks.error) }));
vi.mock('@/util/utils', () => ({ isValidJSON: (text: string) => { try { JSON.parse(text); return true; } catch { return false; } } }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));
vi.mock('@bisheng/ui', async () => {
    const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
    return { ...actual,
        Dropdown: ({ menu, children }: { menu: React.ReactNode; children: React.ReactNode }) => <div>{children}{menu}</div>,
        DropdownItem: ({ onSelect, children }: { onSelect: () => void; children: React.ReactNode }) => <button onClick={onSelect}>{children}</button>,
    };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function setup() {
    const ref = createRef<{ open: () => void }>();
    render(<McpServerEditorDialog ref={ref} onReload={vi.fn()} />);
    act(() => ref.current?.open());
}

it('fills an example without connecting on selection or blur', () => {
    setup();
    fireEvent.click(screen.getByText('tools.gaodeMapSSE'));
    const config = screen.getByPlaceholderText('tools.enterOpenAPISchema');
    expect((config as HTMLTextAreaElement).value).toContain('yourapikey');
    fireEvent.blur(config);
    expect(mocks.parse).not.toHaveBeenCalled();
});

it('validates the filled example on save and does not save after connection failure', async () => {
    mocks.parse.mockRejectedValueOnce(new Error('Connection failed'));
    setup();
    fireEvent.change(screen.getByPlaceholderText('tools.enterMcpName'), { target: { value: 'Map' } });
    fireEvent.click(screen.getByText('tools.gaodeMapStreamable'));
    fireEvent.click(screen.getByText('save'));
    await waitFor(() => expect(mocks.error).toHaveBeenCalled());
    expect(mocks.parse).toHaveBeenCalledTimes(1);
    expect(mocks.create).not.toHaveBeenCalled();
});

it('refreshes explicitly and saves the parsed configuration', async () => {
    mocks.parse.mockResolvedValueOnce({ children: [], description: 'Map tools' });
    mocks.create.mockResolvedValueOnce({ id: 1 });
    setup();
    fireEvent.change(screen.getByPlaceholderText('tools.enterMcpName'), { target: { value: 'Map' } });
    fireEvent.click(screen.getByText('tools.gaodeMapSSE'));
    fireEvent.click(screen.getByText('build.refresh'));
    await waitFor(() => expect(screen.getByText('save')).not.toBeDisabled());
    expect(mocks.parse).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByText('save'));
    await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
    expect(mocks.parse).toHaveBeenCalledTimes(1);
    expect(mocks.create).toHaveBeenCalledWith(expect.objectContaining({ name: 'Map', children: [], openapi_schema: expect.stringContaining('amap-sse') }));
});
