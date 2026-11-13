import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { TreeDepartmentSelect } from './TreeDepartmentSelect';
import zh from '../../../../public/locales/zh-Hans/bs.json';

const mocks = vi.hoisted(() => ({ getPath: vi.fn(), label: 'Organization' }));
vi.mock('@/controllers/API/department', () => ({ getDepartmentPathTreeApi: mocks.getPath }));
vi.mock('./useLazyDepartmentTree', () => ({ useLazyDepartmentTree: () => ({ getNode: () => null, setKeyword: () => {}, reveal: async () => {} }) }));
vi.mock('./LazyDepartmentTree', () => ({ LazyDepartmentTree: () => null }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key === 'bs:department.defaultOrganization' ? mocks.label : key }) }));
beforeEach(() => {
  mocks.label = zh.department.defaultOrganization;
  mocks.getPath.mockReset().mockResolvedValue({ roots: [{ id: 1, dept_id: 'BS@root', name: 'Default Org', children: [{ id: 2, dept_id: 'guests', name: 'Guests' }] }] });
});
it('localizes the selected department path and updates the label when language changes', async () => {
  const view = render(<TreeDepartmentSelect value={2} onChange={vi.fn()} />);
  expect(await screen.findByRole('button', { name: `${mocks.label} / Guests` })).toBeInTheDocument();
  mocks.label = 'Organization';
  view.rerender(<TreeDepartmentSelect value={2} onChange={vi.fn()} />);
  await waitFor(() => expect(screen.getByRole('button', { name: 'Organization / Guests' })).toBeInTheDocument());
  expect(mocks.getPath).toHaveBeenCalledTimes(1);
});
it('keeps a user-renamed root intact', async () => {
  mocks.getPath.mockResolvedValue({ roots: [{ id: 1, dept_id: 'BS@root', name: 'Acme', children: [{ id: 2, dept_id: 'guests', name: 'Guests' }] }] });
  render(<TreeDepartmentSelect value={2} onChange={vi.fn()} />);
  expect(await screen.findByRole('button', { name: 'Acme / Guests' })).toBeInTheDocument();
});
