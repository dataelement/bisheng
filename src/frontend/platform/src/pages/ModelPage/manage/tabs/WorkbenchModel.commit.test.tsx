import { normalizeApiError } from '@bisheng/api-client';
import { QueryClientProvider } from '@tanstack/react-query';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { createPlatformQueryClient } from '@/queryClient';
import WorkbenchModel from './WorkbenchModel';
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- captured props of the mocked ModelManagement
const mocks = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), notice: vi.fn(), toast: vi.fn(), translate: (key: string) => key, managementProps: null as any }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: mocks.translate }) }));
vi.mock('@/controllers/API/finetune', () => ({ getLinsightModelEnvelope: mocks.load, updateLinsightModelConfig: mocks.save }));
vi.mock('@/controllers/request', () => ({ showApiError: mocks.notice }));
vi.mock('@/pages/ModelPage/manage', () => ({ useModel: () => ({ llmOptions: [], embeddings: [], asrModel: [], ttsModel: [] }) }));
vi.mock('@bisheng/ui', async importOriginal => {
  const actual = await importOriginal<typeof import('@bisheng/ui')>();
  return { ...actual, toast: { show: mocks.toast } };
});
vi.mock('@/pages/BuildPage/bench/ModelManagement', () => ({ ModelManagement: (props: unknown) => { mocks.managementProps = props; return null; } }));
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it('acknowledges a committed write once when the following refresh fails', async () => {
  const failure = normalizeApiError({ status_code: 25001 }, { message: 'refresh unavailable' });
  mocks.load.mockResolvedValueOnce({ data: { models: [{ id: '9', displayName: 'Chat' }], embedding_model: { id: '1' } } }).mockRejectedValue(failure);
  mocks.save.mockResolvedValue(undefined);
  const client = createPlatformQueryClient();
  render(<QueryClientProvider client={client}><WorkbenchModel onBack={vi.fn()} /></QueryClientProvider>);
  const save = await screen.findByRole('button', { name: 'model.save' });
  await waitFor(() => expect(save).toBeEnabled());
  fireEvent.click(save);
  await waitFor(() => expect(mocks.load).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(save).toBeEnabled());
  expect(mocks.save).toHaveBeenCalledTimes(1);
  expect(mocks.toast).toHaveBeenCalledWith({ type: 'success', message: 'model.saveSuccess' });
  expect(mocks.notice).toHaveBeenCalledWith(failure);
  expect(client.getQueryData(['linsightModelEnvelope'])).toMatchObject({ data: { embedding_model: { id: '1' } } });
  client.clear();
});
it('moves both defaults along when their row switches to another model', async () => {
  mocks.load.mockResolvedValue({ data: {
    models: [{ key: 'a', id: '9', displayName: 'Chat' }, { key: 'b', id: '10', displayName: 'Other' }],
    embedding_model: { id: '1' }, chat_default_model_id: '9', linsight_default_model_id: '9',
  } });
  mocks.save.mockResolvedValue(undefined);
  const client = createPlatformQueryClient();
  render(<QueryClientProvider client={client}><WorkbenchModel onBack={vi.fn()} /></QueryClientProvider>);
  const save = await screen.findByRole('button', { name: 'model.save' });
  await waitFor(() => expect(save).toBeEnabled());
  await waitFor(() => expect(mocks.managementProps?.chatDefaultModelId).toBe('9'));
  act(() => mocks.managementProps.onModelChange(0, '11'));
  await waitFor(() => expect(mocks.managementProps.chatDefaultModelId).toBe('11'));
  fireEvent.click(save);
  await waitFor(() => expect(mocks.save).toHaveBeenCalledTimes(1));
  expect(mocks.save.mock.calls[0][0]).toMatchObject({
    models: [{ id: '11' }, { id: '10' }],
    chat_default_model_id: '11',
    linsight_default_model_id: '11',
  });
  client.clear();
});
