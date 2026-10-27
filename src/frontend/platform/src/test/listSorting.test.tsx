import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { StrictMode } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { Dialog } from '@/components/bs-ui/dialog';
import VarDialog from '@/components/VariablesComponent/VarDialog';
import ToolsConfig from '@/pages/BuildPage/bench/ToolsConfig';
import OrgKbConfig from '@/pages/BuildPage/bench/OrgKbConfig';
import RecommendedAppsConfig from '@/pages/BuildPage/bench/RecommendedAppsConfig';
import FileUploadSplitStrategy from '@/pages/KnowledgePage/components/FileUploadSplitStrategy';
import Templates from '@/pages/BuildPage/appTemps';
import { installDragDimensions, keyboardDrag } from './keyboardDrag';

const api = vi.hoisted(() => ({ templates: vi.fn(), saveTemplate: vi.fn() }));
vi.mock('@/controllers/API', () => ({
  readFileLibDatabase: vi.fn(async () => ({ data: [] })),
  readTempsDatabase: api.templates,
  updateTempApi: api.saveTemplate,
  deleteTempApi: vi.fn(),
}));
vi.mock('@/controllers/API/tools', () => ({ getToolsApi: vi.fn(async () => []) }));
vi.mock('@/controllers/API/assistant', () => ({
  getChatOnlineApi: vi.fn(async () => ({ list: [], hasMore: false })),
  getRecommendedAppsApi: vi.fn(async () => [{ id: '1', name: 'App One' }, { id: '2', name: 'App Two' }]),
}));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
vi.mock('@/pages/BuildPage/apps', () => ({ SelectType: () => null }));
vi.mock('@/components/bs-comp/cardComponent/avatar', () => ({ default: () => null }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: vi.fn() }));

beforeEach(() => {
  installDragDimensions();
  vi.stubGlobal('requestIdleCallback', (callback: () => void) => setTimeout(callback, 0));
  vi.stubGlobal('cancelIdleCallback', clearTimeout);
  api.templates.mockResolvedValue([
    { id: 1, name: 'Template One', description: '', order_num: 131070 },
    { id: 2, name: 'Template Two', description: '', order_num: 65535 },
  ]);
  api.saveTemplate.mockResolvedValue({});
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.clearAllMocks(); });

it('preserves tool identities, children and default selection when sorting', async () => {
  const tools = [
    { id: 1, name: 'Tool One', default_checked: true, children: [{ id: 11, name: 'Action', tool_key: 'one' }] },
    { id: 2, name: 'Tool Two', default_checked: false, children: [] },
  ];
  const onChange = vi.fn();
  render(<StrictMode><ToolsConfig tools={tools} onChange={onChange} /></StrictMode>);
  await keyboardDrag();
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith([tools[1], tools[0]]);
});

it('normalises knowledge base sort positions without changing default flags', async () => {
  const orgKbs = [
    { id: 1, name: 'Knowledge One', default_checked: true, sort_order: 0 },
    { id: 2, name: 'Knowledge Two', default_checked: false, sort_order: 1 },
  ];
  const onChange = vi.fn();
  render(<StrictMode><OrgKbConfig orgKbs={orgKbs} onChange={onChange} /></StrictMode>);
  await keyboardDrag();
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith([{ ...orgKbs[1], sort_order: 0 }, { ...orgKbs[0], sort_order: 1 }]);
});

it('emits recommended app IDs in the dragged order after details load', async () => {
  const onChange = vi.fn();
  render(<StrictMode><RecommendedAppsConfig selectedAppIds={['1', '2']} onSelectedAppsChange={onChange} /></StrictMode>);
  await screen.findByText('App One');
  await keyboardDrag();
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith(['2', '1']);
});

it('preserves split rule regex, position and ID after sorting', async () => {
  const rules = [
    { id: 'a', regex: '\\n', position: 'after', rule: 'Newline' },
    { id: 'b', regex: 'HEADER', position: 'before', rule: 'Heading' },
  ];
  const onChange = vi.fn();
  render(<StrictMode><FileUploadSplitStrategy data={rules} onChange={onChange} /></StrictMode>);
  await keyboardDrag();
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith([rules[1], rules[0]]);
});

it('does not persist a split rule order when dropped in place', async () => {
  const onChange = vi.fn();
  render(<StrictMode><FileUploadSplitStrategy data={[
    { id: 'a', regex: '\\n', position: 'after', rule: 'Newline' },
    { id: 'b', regex: 'HEADER', position: 'before', rule: 'Heading' },
  ]} onChange={onChange} /></StrictMode>);
  await keyboardDrag(0, false, false);
  expect(onChange).not.toHaveBeenCalled();
});

it('does not persist a recommended app order when dropped in place', async () => {
  const onChange = vi.fn();
  render(<StrictMode><RecommendedAppsConfig selectedAppIds={['1', '2']} onSelectedAppsChange={onChange} /></StrictMode>);
  await screen.findByText('App One');
  await keyboardDrag(0, false, false);
  expect(onChange).not.toHaveBeenCalled();
});

it('keeps variable edits local until explicit save and preserves option keys', async () => {
  const onSave = vi.fn();
  render(<StrictMode><Dialog open><VarDialog
    data={{ type: 'select', name: 'Variable', options: [{ key: 'a', value: 'First' }, { key: 'b', value: 'Second' }] }}
    onSave={onSave} onClose={vi.fn()}
  /></Dialog></StrictMode>);
  await keyboardDrag();
  expect(onSave).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'save' }));
  expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ options: [{ key: 'b', value: 'Second' }, { key: 'a', value: 'First' }] }));
});

it('persists only the moved template using the existing order-number protocol', async () => {
  render(<StrictMode><MemoryRouter initialEntries={['/build/temps/10']}><Routes><Route path="/build/temps/:type" element={<Templates />} /></Routes></MemoryRouter></StrictMode>);
  await screen.findByText('Template One');
  await keyboardDrag();
  await waitFor(() => expect(api.saveTemplate).toHaveBeenCalledTimes(1));
  expect(api.saveTemplate).toHaveBeenCalledWith(1, { name: 'Template One', description: '', order_num: 0 });
});
