import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createRef, type ComponentRef } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { TestDialog } from './EditTool';

const mocks = vi.hoisted(() => ({ saved: vi.fn(), temporary: vi.fn(), toast: vi.fn() }));
vi.mock('@/controllers/API/tools', () => ({ testSavedToolApi: mocks.saved, testToolApi: mocks.temporary }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@bisheng/ui', async () => ({
    ...await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui'),
    toast: { show: mocks.toast },
}));

const operation = { id: 7, name: 'search', extra: '{}', api_params: [{ id: 8, name: 'count', required: false }] };
const tool = { id: 4, children: [operation], auth_method: 1, auth_type: 'bearer', openapi_schema: 'saved schema' };

afterEach(() => { cleanup(); vi.clearAllMocks(); });

function openTest(apiKey: string, schemaContent = tool.openapi_schema) {
    const ref = createRef<ComponentRef<typeof TestDialog>>();
    const formState = { apiKey, schemaContent, authMethod: 'apikey', authType: 'bearer' };
    render(<TestDialog ref={ref} tool={tool} formState={formState} />);
    act(() => ref.current?.open(operation, tool, formState));
    fireEvent.click(screen.getByRole('button', { name: 'test.test' }));
}

it('tests the saved operation with only its IDs and parameters when the key is masked', async () => {
    mocks.saved.mockResolvedValue('saved response');
    openTest('********');
    expect(await screen.findByDisplayValue('saved response')).toBeInTheDocument();
    expect(mocks.saved).toHaveBeenCalledWith(4, 7, {});
    expect(mocks.temporary).not.toHaveBeenCalled();
});

it('asks for a key before testing a modified configuration', () => {
    openTest('********', 'changed schema');
    expect(mocks.toast).toHaveBeenCalledWith({ type: 'warning', message: 'test.enterKeyForChangedConfiguration' });
    expect(mocks.saved).not.toHaveBeenCalled();
    expect(mocks.temporary).not.toHaveBeenCalled();
});

it('tests with a newly entered key through the existing temporary endpoint', async () => {
    mocks.temporary.mockResolvedValue('temporary response');
    openTest('new-key');
    expect(await screen.findByDisplayValue('temporary response')).toBeInTheDocument();
    expect(mocks.temporary).toHaveBeenCalledWith(expect.objectContaining({ api_key: 'new-key' }));
    expect(mocks.saved).not.toHaveBeenCalled();
});
