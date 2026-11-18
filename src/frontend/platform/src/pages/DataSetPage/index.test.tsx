import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import DataSetPage from './index';

const mocks = vi.hoisted(() => ({ list: vi.fn(), remove: vi.fn(), downloadUrl: vi.fn(), download: vi.fn(), confirm: vi.fn(), user: { user_id: 7, tenant_id: 1 }, scope: 1 }));
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: mocks.user }) }));
vi.mock('@/controllers/API/finetune', () => ({ getPresetFileApi: mocks.list, deleteDatasetApi: mocks.remove, getFileUrlApi: mocks.downloadUrl }));
vi.mock('@/components/bs-comp/FileView', () => ({ checkSassUrl: (url: string) => url }));
vi.mock('./CreateDataSet', () => ({ default: () => null }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: mocks.confirm }));
vi.mock('@/util/utils', () => ({ downloadFile: mocks.download }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.scope = 1;
  mocks.list.mockImplementation(async () => ({ data: [{ id: String(mocks.scope), name: `dataset-${mocks.scope}`, create_time: '2026-11-19T00:00:00', update_time: '2026-11-19T00:00:00', user_name: 'Owner', url: `dataset/${mocks.scope}.json` }], total: 1 }));
});

it('retires a deletion confirmation opened in the previous management view', async () => {
  render(<DataSetPage />);
  await screen.findByText('dataset-1');
  fireEvent.click(screen.getByRole('button', { name: 'delete' }));
  const { onOk } = mocks.confirm.mock.calls[0][0];
  mocks.scope = 60;
  act(() => window.dispatchEvent(new Event('bisheng:management-scope-changed')));
  await screen.findByText('dataset-60');
  const close = vi.fn();
  await onOk(close);
  expect(close).toHaveBeenCalledOnce();
  expect(mocks.remove).not.toHaveBeenCalled();
});

it('ignores an old signed download response after switching management views', async () => {
  let finish!: (value: { url: string }) => void;
  mocks.downloadUrl.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  render(<DataSetPage />);
  await screen.findByText('dataset-1');
  fireEvent.click(screen.getByRole('button', { name: 'dataset.download' }));
  await waitFor(() => expect(mocks.downloadUrl).toHaveBeenCalledWith('dataset/1.json'));
  mocks.scope = 60;
  act(() => window.dispatchEvent(new Event('bisheng:management-scope-changed')));
  await screen.findByText('dataset-60');
  await act(async () => finish({ url: 'https://objects.test/old.json' }));
  expect(mocks.download).not.toHaveBeenCalled();
});
afterEach(cleanup);

it('retires old rows and reloads after a management view changes without changing the login Home', async () => {
  render(<DataSetPage />);
  await screen.findByText('dataset-1');
  let finish!: (value: { data: never[]; total: number }) => void;
  mocks.list.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  mocks.scope = 60;
  act(() => window.dispatchEvent(new Event('bisheng:management-scope-changed')));
  expect(screen.queryByText('dataset-1')).not.toBeInTheDocument();
  await waitFor(() => expect(mocks.list).toHaveBeenCalledTimes(2));
  mocks.scope = 70;
  act(() => window.dispatchEvent(new Event('bisheng:management-scope-changed')));
  await screen.findByText('dataset-70');
  await act(async () => finish({ data: [], total: 0 }));
  expect(screen.getByText('dataset-70')).toBeVisible();
  expect(mocks.list).toHaveBeenLastCalledWith({ page_size: 20, page_num: 1, keyword: '' });
});
