import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import { DepartmentProviderBatch } from '@/pages/KnowledgePage/components/DepartmentProviderBatch';
import * as api from '@/controllers/API/departmentKnowledgeSpace';

vi.mock('@/hooks/useKnowledgePageScope', () => ({useKnowledgePageScope: () => ({ scopes: { admin: { tenantId: 31, identityKey: 'user:4' } }, canManage: true })}));
vi.mock('react-i18next', async original => ({...await original<typeof import('react-i18next')>(), useTranslation: () => ({t: (key: string) => key})}));
vi.mock('@/controllers/API/departmentKnowledgeSpace', () => ({
  previewDepartmentPreset: vi.fn(),
  createExternalDepartmentBatch: vi.fn(),
  getExternalDepartmentBatchStatus: vi.fn(),
  listProviderModels: vi.fn(),
  listExtractTemplates: vi.fn(),
}));
afterEach(() => sessionStorage.clear());
const models = {chat: [{id: 's', name: 'qwen', display_name: 'Qwen'}], embedding: [{id: 'e', name: 'bge', display_name: 'BGE', dimension: 1024}], vision: [{id: 'v', name: 'vl', display_name: 'VL'}]};
const selection = {summary_model_id: 's', embedding_model_id: 'e', vision_model_id: 'v', chunk_size: 512, overlap: 64, extract_template_kb_id: 'tpl'};

it('cannot preview while the WeKnora model list is unavailable', async () => {
  vi.mocked(api.listProviderModels).mockRejectedValue(new Error('down'));
  vi.mocked(api.listExtractTemplates).mockResolvedValue([{id: 'tpl', name: 'Template'}]);
  render(<DepartmentProviderBatch ids={[3]} />);
  await screen.findByText('departmentSpace.modelsFailed');
  expect(screen.getByText('departmentSpace.batchPreview').closest('button')?.disabled).toBe(true);
  expect(api.previewDepartmentPreset).not.toHaveBeenCalled();
});

it('confirms the reviewed preset once and reopens partial results without creating again', async () => {
  const result: api.DepartmentReceipt[] = [{departmentId:3,status:'confirmed'}, {departmentId:5,status:'failed'}];
  vi.mocked(api.listProviderModels).mockResolvedValue(models);
  vi.mocked(api.listExtractTemplates).mockResolvedValue([{id: 'tpl', name: 'Template'}]);
  vi.mocked(api.previewDepartmentPreset).mockResolvedValue({preset_revision:2, ...selection});
  vi.mocked(api.createExternalDepartmentBatch).mockResolvedValue(result);
  vi.mocked(api.getExternalDepartmentBatchStatus).mockResolvedValue([result[0], {departmentId:5,status:'unconfirmed'}]);
  const first = render(<DepartmentProviderBatch ids={[3,5]} />);
  const preview = screen.getByText('departmentSpace.batchPreview').closest('button')!;
  await waitFor(() => expect(preview.disabled).toBe(false));
  fireEvent.click(preview);
  fireEvent.click(await screen.findByText('departmentSpace.createAction'));
  await screen.findByText(/batchStatus.failed/);
  expect(api.previewDepartmentPreset).toHaveBeenCalledWith(31, 3, selection);
  expect(api.createExternalDepartmentBatch).toHaveBeenCalledTimes(1);
  const key = vi.mocked(api.createExternalDepartmentBatch).mock.calls[0][2];
  expect(vi.mocked(api.createExternalDepartmentBatch).mock.calls[0][4]).toEqual(selection);
  first.unmount();
  render(<DepartmentProviderBatch ids={[]} />);
  await waitFor(() => expect(api.getExternalDepartmentBatchStatus).toHaveBeenCalledWith(31, [3,5], key));
  await screen.findByText(/batchStatus.confirmed/);
  await screen.findByText(/batchStatus.failed/);
  expect(api.createExternalDepartmentBatch).toHaveBeenCalledTimes(1);
});
