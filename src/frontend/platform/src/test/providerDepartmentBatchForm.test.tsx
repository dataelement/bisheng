import { fireEvent, render, screen, waitFor } from '@/test/test-utils';
import { afterEach, expect, it, vi } from 'vitest';
import { DepartmentProviderBatch } from '@/pages/KnowledgePage/components/DepartmentProviderBatch';
import * as api from '@/controllers/API/departmentKnowledgeSpace';

vi.mock('@/hooks/useKnowledgePageScope', () => ({useKnowledgePageScope: () => ({ scopes: { admin: { tenantId: 31, identityKey: 'user:4' } }, canManage: true })}));
vi.mock('react-i18next', async original => ({...await original<typeof import('react-i18next')>(), useTranslation: () => ({t: (key: string) => key})}));
vi.mock('@/controllers/API/departmentKnowledgeSpace', () => ({previewDepartmentPreset: vi.fn(), createExternalDepartmentBatch: vi.fn(), getExternalDepartmentBatchStatus: vi.fn()}));
afterEach(() => sessionStorage.clear());

it('confirms the reviewed preset once and reopens partial results without creating again', async () => {
  const result: api.DepartmentReceipt[] = [{departmentId:3,status:'confirmed'}, {departmentId:5,status:'failed'}];
  vi.mocked(api.previewDepartmentPreset).mockResolvedValue({preset_revision:2});
  vi.mocked(api.createExternalDepartmentBatch).mockResolvedValue(result);
  vi.mocked(api.getExternalDepartmentBatchStatus).mockResolvedValue([result[0], {departmentId:5,status:'unconfirmed'}]);
  const first = render(<DepartmentProviderBatch ids={[3,5]} />);
  fireEvent.click(screen.getByText('departmentSpace.batchPreview'));
  fireEvent.click(await screen.findByText('departmentSpace.createAction'));
  await screen.findByText(/batchStatus.failed/);
  expect(api.createExternalDepartmentBatch).toHaveBeenCalledTimes(1);
  const key = vi.mocked(api.createExternalDepartmentBatch).mock.calls[0][2];
  first.unmount();
  render(<DepartmentProviderBatch ids={[]} />);
  await waitFor(() => expect(api.getExternalDepartmentBatchStatus).toHaveBeenCalledWith(31, [3,5], key));
  await screen.findByText(/batchStatus.confirmed/);
  await screen.findByText(/batchStatus.failed/);
  expect(api.createExternalDepartmentBatch).toHaveBeenCalledTimes(1);
});
