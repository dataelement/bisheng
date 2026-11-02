import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import CardComponent from '@/components/bs-comp/cardComponent';
import { AppType } from '@/types/app';
import { requiresManagementScope } from '@/controllers/managementScope';
import Templates from '@/pages/BuildPage/appTemps';
import { canManageAppTemplates } from '@/pages/BuildPage/templatePermissions';

const state = vi.hoisted(() => ({ user: {} as Record<string, unknown>, list: vi.fn() }));
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({
  get user() { return state.user; },
}) }));
vi.mock('@/controllers/API', () => ({ readTempsDatabase: state.list, deleteTempApi: vi.fn(), updateTempApi: vi.fn() }));
vi.mock('@/pages/BuildPage/apps', () => ({ SelectType: () => null }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));

vi.mock('react-i18next', () => ({ useTranslation: () => ({
  t: (key: string) => key, i18n: { t: (key: string) => key, language: 'en' },
}) }));
vi.mock('@/components/bs-icons/user', () => ({ UserIcon: () => null }));
vi.mock('bisheng-icons', async (original) => {
  const actual = await original<typeof import('bisheng-icons')>();
  return { ...actual, Outlined: { ...actual.Outlined, Setting: () => null } };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

describe('template actions', () => {
  it.each([
    [{ is_global_super: true }, true], [{ is_child_admin: true }, true], [{ role: 'admin' }, true],
    [{ web_menu: ['create_app'], is_department_admin: true }, false], [{ role: 'editor' }, false],
  ])('uses admin identity instead of creation or department permissions (%j)', (user, expected) => {
    expect(canManageAppTemplates(user)).toBe(expected);
  });
  it.each([AppType.ASSISTANT, AppType.FLOW])('allows a tenant admin to template %s', async (type) => {
    const add = vi.fn();
    render(<CardComponent id="source" data={{ id: 'source' }} title="Source" description=""
      type={type} edit isAdmin={false} canAddTemplate onAddTemp={add} showSwitch={false} />);
    await userEvent.click(screen.getByRole('button', { name: 'more' }));
    await userEvent.click(screen.getByText('skills.createTemplate'));
    expect(add).toHaveBeenCalledWith({ id: 'source' });
  });

  it('does not infer template management from application edit permission', () => {
    render(<CardComponent id="source" data={{}} title="Source" description=""
      type={AppType.FLOW} edit canAddTemplate={false} onAddTemp={vi.fn()} showSwitch={false} />);
    expect(screen.queryByRole('button', { name: 'more' })).not.toBeInTheDocument();
  });

  it.each([
    ['post', '/api/v1/skill/template/create'],
    ['post', '/api/v1/skill/template/21'],
    ['delete', '/api/v1/skill/template/21'],
  ])('pins the management tenant on %s %s', (method, url) => {
    expect(requiresManagementScope(method, url)).toBe(true);
  });
});

function managementPage() {
  return render(<MemoryRouter initialEntries={['/build/temps/flow']}><Routes>
    <Route path="/build/temps/:type" element={<Templates />} />
    <Route path="/403" element={<div>Forbidden</div>} />
  </Routes></MemoryRouter>);
}

it('refuses direct management page access for a create-app user before loading templates', async () => {
  state.user = { role: 'editor', web_menu: ['create_app'] };
  state.list.mockResolvedValue([]);
  managementPage();
  await screen.findByText('Forbidden');
  expect(state.list).not.toHaveBeenCalled();
});

it('clears old templates and ignores a stale response when management tenant changes', async () => {
  state.user = { is_child_admin: true, tenant_id: 2 };
  let resolveOld!: (value: unknown) => void;
  state.list.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve; }))
    .mockResolvedValueOnce([{ id: 301, name: 'New tenant template', order_num: 1 }]);
  managementPage();
  await waitFor(() => expect(state.list).toHaveBeenCalledTimes(1));
  act(() => { window.dispatchEvent(new Event('bisheng:management-scope-changed')); });
  await screen.findByText('New tenant template');
  await act(async () => { resolveOld([{ id: 201, name: 'Old tenant template', order_num: 1 }]); });
  expect(screen.queryByText('Old tenant template')).not.toBeInTheDocument();
  expect(screen.getByText('New tenant template')).toBeInTheDocument();
});
