import { createContext } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { Finetune } from './finetune';
import { userContext } from '@/contexts/userContext';

const mock = vi.hoisted(() => ({ serviceManagement: vi.fn(), tenant: 60 }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key, i18n: { loadNamespaces: vi.fn() } }) }));
vi.mock('@/contexts/userContext', () => ({ userContext: createContext({ user: {} }) }));
vi.mock('@/hooks/useKnowledgePageScope', () => ({ useKnowledgePageScope: () => ({ scopes: { ordinary: { identityKey: 'user:849', tenantId: mock.tenant, managementTenantId: mock.tenant } } }) }));
vi.mock('@/util/hook', () => ({ useDebounce: (fn: unknown) => fn, useTable: () => ({ page: 1, pageSize: 10, data: [], total: 0 }) }));
vi.mock('@/controllers/API/finetune', () => ({ getTasksApi: vi.fn(), deleteTaskApi: vi.fn() }));
vi.mock('./components/FinetuneHead', () => ({ FinetuneHead: ({ rtClick, onCreate }: { rtClick?: () => void; onCreate: () => void }) => <><button onClick={onCreate}>Create task</button>{rtClick && <button onClick={rtClick}>Manage services</button>}</> }));
vi.mock('./components/CreateTask', () => ({ CreateTask: ({ rtClick }: { rtClick?: () => void }) => <div>Task form{rtClick && <span>Form service management</span>}</div> }));
vi.mock('./components/RTConfig', () => ({ RTConfig: () => { mock.serviceManagement(); return null; } }));
vi.mock('./components/FinetuneDetail', () => ({ FinetuneDetail: () => null, BadgeView: () => null }));
vi.mock('./cpuInfo', () => ({ CpuDetail: () => null }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });

function View({ admin = false }: { admin?: boolean }) {
    return <userContext.Provider value={{ user: { user_id: 849, web_menu: ['model'], is_child_admin: admin } } as React.ContextType<typeof userContext>}><Finetune /></userContext.Provider>;
}

it('allows ordinary task creation without mounting the admin-only service dialog', () => {
    render(<View />);
    expect(screen.queryByText('Manage services')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Create task'));
    expect(screen.getByText('Task form')).toBeVisible();
    expect(screen.queryByText('Form service management')).not.toBeInTheDocument();
    expect(mock.serviceManagement).not.toHaveBeenCalled();
});

it('retains admin management and removes a stale task form on tenant change', () => {
    const { rerender } = render(<View admin />);
    expect(screen.getByText('Manage services')).toBeVisible();
    fireEvent.click(screen.getByText('Create task'));
    expect(screen.getByText('Form service management')).toBeVisible();
    mock.tenant = 70;
    rerender(<View admin />);
    expect(screen.queryByText('Task form')).not.toBeInTheDocument();
    expect(mock.serviceManagement).toHaveBeenCalled();
    mock.tenant = 60;
});
