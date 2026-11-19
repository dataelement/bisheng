import { createContext } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import Management from './index';
import { userContext } from '@/contexts/userContext';

const mock = vi.hoisted(() => ({ multi: false, modelConfig: vi.fn(), systemConfig: vi.fn() }));
vi.mock('@/contexts/userContext', () => ({ userContext: createContext({ user: {} }) }));
vi.mock('@/contexts/locationContext', () => ({ locationContext: createContext({ appConfig: { get multiTenantEnabled() { return mock.multi; } } }) }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { loadNamespaces: vi.fn() } }) }));
vi.mock('@/hooks/useKnowledgePageScope', () => ({ useKnowledgePageScope: () => ({ scopes: { ordinary: { identityKey: 'user:849', tenantId: 60, managementTenantId: 60 } } }) }));
vi.mock('@tanstack/react-query', () => ({ useQuery: () => ({ data: {}, refetch: vi.fn() }) }));
vi.mock('@/controllers/API/finetune', () => ({
    getModelListApi: vi.fn().mockResolvedValue([{ id: 60, name: 'Tenant provider', models: [{ id: 600, model_name: 'Chat', model_type: 'llm', status: 1, online: true }] }]),
    getAssistantModelList: vi.fn(), changeLLmServerStatus: vi.fn(), verifyLLmModelStatus: vi.fn(),
}));
vi.mock('./ModelConfig', () => ({ default: () => { mock.modelConfig(); return <div>Model editor</div>; } }));
vi.mock('./SystemModelConfig', () => ({ default: () => { mock.systemConfig(); return <div>System settings</div>; } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function View({ admin = false, query = '' }: { admin?: boolean; query?: string }) {
    return <MemoryRouter initialEntries={['/model' + query]}><userContext.Provider value={{ user: { web_menu: ['model'], is_child_admin: admin } } as React.ContextType<typeof userContext>}><Management /></userContext.Provider></MemoryRouter>;
}

it.each([false, true])('shows an ordinary model-menu user a read-only list (multi-tenant: %s)', async multi => {
    mock.multi = multi;
    render(<View query="?systemModel=knowledge" />);
    fireEvent.click(await screen.findByRole('button', { name: 'Tenant provider' }));
    expect(screen.getByText('Chat')).toBeVisible();
    expect(screen.getByRole('switch')).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'model.updateStatus' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'model.modelConfiguration' })).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'model.addModel' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'model.systemModelSettings' })).not.toBeInTheDocument();
    expect(mock.systemConfig).not.toHaveBeenCalled();
    expect(mock.modelConfig).not.toHaveBeenCalled();
});

it('retains model and system settings entries for the tenant admin', async () => {
    render(<View admin />);
    expect(await screen.findByRole('button', { name: 'model.addModel' })).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'model.systemModelSettings' }));
    expect(screen.getByText('System settings')).toBeVisible();
});
