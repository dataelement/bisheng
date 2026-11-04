import React, { createRef } from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { Accordion } from '@/components/bs-ui/accordion';
import AssistantSetting, { type AssistantSettingRef } from '@/components/Pro/security/AssistantSetting';

const api = vi.hoisted(() => ({ load: vi.fn(), save: vi.fn(), error: vi.fn() }));
vi.mock('@/controllers/API/pro', () => ({ getSensitiveApi: api.load, sensitiveSaveApi: api.save }));
vi.mock('@/controllers/request', () => ({ showApiError: api.error }));
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }));
vi.mock('i18next', () => ({ t: (key: string) => key }));

const empty = { is_check: false, words_type: null, words: '', auto_reply: '' };
const valid = { is_check: false, words_type: ['1'], words: '', auto_reply: 'Blocked' };
function mount(id: string | number = 'workflow') {
  const ref = createRef<AssistantSettingRef>();
  render(<Accordion type="single" collapsible><AssistantSetting ref={ref} id={id} type={5} /></Accordion>);
  return ref;
}
async function loaded() {
  await waitFor(() => expect(screen.getByRole('switch', { hidden: true })).not.toBeDisabled());
}
function fill() {
  fireEvent.click(screen.getByLabelText('build.builtinWordList'));
  fireEvent.change(screen.getByPlaceholderText('build.defaultAutoReply'), { target: { value: 'Blocked' } });
}
beforeEach(() => { vi.clearAllMocks(); api.load.mockResolvedValue(empty); api.save.mockResolvedValue({}); });
afterEach(cleanup);

it('opens incomplete configuration without enabling or saving, and cancellation keeps it off', async () => {
  mount(); await loaded();
  fireEvent.click(screen.getByRole('switch', { hidden: true }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByRole('switch', { hidden: true })).not.toBeChecked();
  expect(api.save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'cancel' }));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('switch', { hidden: true })).not.toBeChecked();
  fireEvent.click(screen.getByRole('switch', { hidden: true }));
  expect(screen.getByPlaceholderText('build.defaultAutoReply')).toHaveValue('');
});

it('enables only after saving valid configuration succeeds and prevents duplicate saves', async () => {
  let finish!: (value: object) => void;
  api.save.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  mount(); await loaded(); fireEvent.click(screen.getByRole('switch', { hidden: true })); fill();
  fireEvent.click(screen.getByRole('button', { name: 'save' }));
  expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ isCheck: true, wordsType: [1], autoReply: 'Blocked' }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByRole('switch', { hidden: true })).not.toBeChecked();
  expect(screen.getByRole('button', { name: 'save' })).toBeDisabled();
  fireEvent.click(screen.getByRole('button', { name: 'save' }));
  fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
  expect(api.save).toHaveBeenCalledTimes(1);
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  await act(async () => finish({}));
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(screen.getByRole('switch', { hidden: true })).toBeChecked();
});

it('preserves the draft after a failed save and allows retry', async () => {
  api.save.mockRejectedValueOnce(new Error('offline'));
  mount(); await loaded(); fireEvent.click(screen.getByRole('switch', { hidden: true })); fill();
  fireEvent.click(screen.getByRole('button', { name: 'save' }));
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(screen.getByPlaceholderText('build.defaultAutoReply')).toHaveValue('Blocked');
  expect(screen.getByRole('switch', { hidden: true })).not.toBeChecked();
  fireEvent.click(screen.getByRole('button', { name: 'save' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getByRole('switch', { hidden: true })).toBeChecked();
});

it('reuses valid saved configuration and retains the enabled state when disabling fails', async () => {
  api.load.mockResolvedValue(valid); mount(); await loaded();
  fireEvent.click(screen.getByRole('switch', { hidden: true }));
  await waitFor(() => expect(screen.getByRole('switch', { hidden: true })).toBeChecked());
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ wordsType: [1], isCheck: true }));
  const settings = screen.getByRole('button', { name: 'build.contentSecuritySettings' });
  expect(settings.querySelector('svg')).toHaveClass('size-4');
  api.save.mockRejectedValueOnce(new Error('offline'));
  fireEvent.click(screen.getByRole('switch', { hidden: true }));
  await waitFor(() => expect(api.error).toHaveBeenCalled());
  expect(screen.getByRole('switch', { hidden: true })).toBeChecked();
});

it('requires custom words before enabling even when the word type and reply are present', async () => {
  api.load.mockResolvedValue({ ...valid, words_type: [2], words: '   ' });
  mount(); await loaded(); fireEvent.click(screen.getByRole('switch', { hidden: true }));
  expect(screen.getByRole('dialog')).toBeInTheDocument();
  expect(api.save).not.toHaveBeenCalled();
});

it('keeps new-application settings local until the application gets an id', async () => {
  const ref = mount('');
  fireEvent.click(screen.getByRole('switch', { hidden: true })); fill();
  fireEvent.click(screen.getByRole('button', { name: 'save' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(api.save).not.toHaveBeenCalled();
  await act(async () => { expect(await ref.current!.create(77)).toBe(true); });
  expect(api.save).toHaveBeenCalledWith(expect.objectContaining({ id: 77, isCheck: true, wordsType: [1] }));
});

it('does not allow enabling before the saved configuration finishes loading', async () => {
  let finish!: (value: typeof valid) => void;
  api.load.mockReturnValue(new Promise(resolve => { finish = resolve; }));
  mount();
  expect(screen.getByRole('switch', { hidden: true })).toBeDisabled();
  fireEvent.click(screen.getByRole('switch', { hidden: true }));
  expect(api.save).not.toHaveBeenCalled();
  await act(async () => finish(valid));
  expect(screen.getByRole('switch', { hidden: true })).not.toBeDisabled();
});

it('rejects incomplete settings locally without closing the editor', async () => {
  mount(); await loaded(); fireEvent.click(screen.getByRole('switch', { hidden: true }));
  fireEvent.change(screen.getByPlaceholderText('build.defaultAutoReply'), { target: { value: '   ' } });
  fireEvent.click(screen.getByRole('button', { name: 'save' }));
  await waitFor(() => expect(screen.getByRole('button', { name: 'save' })).not.toBeDisabled());
  expect(api.save).not.toHaveBeenCalled();
  expect(screen.getByRole('dialog')).toBeInTheDocument();
});
