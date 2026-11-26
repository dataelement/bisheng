import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import DataSetPage from './index';

const mocks = vi.hoisted(() => ({ list: vi.fn(), remove: vi.fn(), downloadUrl: vi.fn(), download: vi.fn(), confirm: vi.fn(), convert: vi.fn(), user: { user_id: 7, tenant_id: 1, leaf_tenant_id: 1 }, scope: 1 }));
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: mocks.user }) }));
vi.mock('@/controllers/API/finetuneDatasets', () => ({ listDatasetCatalog: mocks.list, deleteCatalogDataset: mocks.remove, downloadCatalogDataset: mocks.downloadUrl, convertCatalogDataset: mocks.convert }));
vi.mock('@/pages/ModelPage/components/DatasetImportDialog', () => ({ DatasetImportDialog: () => null }));
vi.mock('@/pages/ModelPage/components/SavedDatasetPreview', () => ({ SavedDatasetPreview: () => null }));
vi.mock('@/components/bs-comp/FileView', () => ({ checkSassUrl: (url: string) => url }));
vi.mock('./CreateDataSet', () => ({ default: () => null }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: mocks.confirm }));
vi.mock('@/util/utils', () => ({ downloadFile: mocks.download }));

beforeEach(() => {
  vi.clearAllMocks();
  mocks.scope = 1;
  mocks.user.leaf_tenant_id = 1;
  mocks.list.mockImplementation(async () => ({ data: [{ id: String(mocks.scope), data_type: 'text', source_type: 'local', name: `dataset-${mocks.scope}`, create_time: '2026-11-19T00:00:00', update_time: '2026-11-19T00:00:00', user_name: 'Owner', url: `dataset/${mocks.scope}.json` }], total: 1 }));
});

it('retires a deletion confirmation opened in the previous management view', async () => {
  render(<DataSetPage />);
  await screen.findByText('dataset-1');
  fireEvent.click(screen.getByRole('button', { name: 'bs:delete' }));
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
  fireEvent.click(screen.getByRole('button', { name: 'bs:dataset.download' }));
  await waitFor(() => expect(mocks.downloadUrl).toHaveBeenCalledWith('1'));
  mocks.scope = 60;
  act(() => window.dispatchEvent(new Event('bisheng:management-scope-changed')));
  await screen.findByText('dataset-60');
  await act(async () => finish({ url: 'https://objects.test/old.json' }));
  expect(mocks.download).not.toHaveBeenCalled();
});
afterEach(cleanup);

it('retires the current dataset view when the same person changes home tenant', async () => {
  const view = render(<DataSetPage />);
  await screen.findByText('dataset-1');
  mocks.scope = 60;
  mocks.user.leaf_tenant_id = 60;
  view.rerender(<DataSetPage />);
  expect(screen.queryByText('dataset-1')).not.toBeInTheDocument();
  await screen.findByText('dataset-60');
});

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
  expect(mocks.list).toHaveBeenLastCalledWith({ page: 1, limit: 20, keyword: '' });
});


it('filters task-independent catalog categories and keeps the legacy row after explicit conversion', async () => {
  const legacy = { id: 'old', data_type: 'legacy', source_type: 'ftp', name: 'legacy-record', create_time: '2026-11-26', update_time: '2026-11-26', url: 'old.json' };
  const text = { ...legacy, id: 'new', data_type: 'text', name: 'converted-record' };
  let converted = false;
  mocks.list.mockImplementation(async ({ data_type }: { data_type?: string }) => {
    const rows = (converted ? [legacy, text] : [legacy]).filter(row => !data_type || row.data_type === data_type);
    return { data: rows, total: rows.length };
  });
  mocks.convert.mockImplementation(async () => { converted = true; });
  render(<DataSetPage />);
  await screen.findByText('legacy-record');
  expect(screen.getByText('finetune.datasetSource_ftp')).toBeVisible();
  fireEvent.click(screen.getByRole('button', { name: 'finetune.convertToText' }));
  await screen.findByText('converted-record');
  expect(screen.getByText('legacy-record')).toBeVisible();
  expect(mocks.convert).toHaveBeenCalledWith('old');
  fireEvent.click(screen.getByRole('combobox', { name: 'finetune.datasetCategory' }));
  fireEvent.click(await screen.findByRole('option', { name: 'finetune.type_text' }));
  await waitFor(() => expect(mocks.list).toHaveBeenLastCalledWith({ page: 1, limit: 20, keyword: '', data_type: 'text' }));
  await waitFor(() => expect(screen.queryByText('legacy-record')).not.toBeInTheDocument());
  expect(screen.getByText('converted-record')).toBeVisible();
});
