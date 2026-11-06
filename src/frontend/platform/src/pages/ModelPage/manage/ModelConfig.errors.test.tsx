import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { getLLmServerDetail } from '@/controllers/API/finetune';
import ModelConfig from './ModelConfig';
vi.mock('@/controllers/API/finetune', () => ({ getLLmServerDetail: vi.fn(), addLLmServer: vi.fn(), updateLLmServer: vi.fn(), deleteLLmServer: vi.fn() }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('./tabs/WorkbenchModel', () => ({ useLinsightConfig: () => ({ refetch: vi.fn() }) }));
vi.mock('./CustomForm', () => ({ CustomForm: () => null }));
vi.mock('./useLink', () => ({ useModelProviderInfo: () => null }));
vi.mock('@/hooks/useAdminScope', () => ({ useAdminScope: () => ({ scope: { scope_tenant_id: null } }) }));
vi.mock('@/contexts/userContext', async () => {
    const { createContext } = await import('react');
    return { userContext: createContext({ user: {} }) };
});
vi.mock('@/contexts/locationContext', async () => {
    const { createContext } = await import('react');
    return { locationContext: createContext({ appConfig: { multiTenantEnabled: false } }) };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('shows a failed provider load instead of an editable default form and retries it', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }));
    vi.mocked(getLLmServerDetail).mockRejectedValueOnce(new Error('Provider unavailable')).mockResolvedValueOnce({ id: 7, name: 'Provider', type: 'openai', models: [], config: {} });
    render(<ModelConfig id={7} onGetName={vi.fn()} onBack={vi.fn()} onReload={vi.fn()} onBerforSave={vi.fn()} onAfterSave={vi.fn()} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Provider unavailable');
    expect(screen.queryByRole('button', { name: 'model.save' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(await screen.findByDisplayValue('Provider')).toBeInTheDocument();
    expect(getLLmServerDetail).toHaveBeenCalledTimes(2);
});
