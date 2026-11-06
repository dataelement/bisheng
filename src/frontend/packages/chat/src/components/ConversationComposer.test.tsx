import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { createRef } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import { ConversationComposer } from './ConversationComposer';
afterEach(cleanup);
const labels = { send: 'Send', stop: 'Stop', restart: 'Restart' };
it('owns one aligned attachment, voice and send toolbar and guards attachment selection', () => {
  const onAttach = vi.fn(); const inputRef = createRef<HTMLTextAreaElement>();
  const { rerender } = render(<ConversationComposer inputRef={inputRef} canExecute labels={{ ...labels, attach: 'Attach' }} onSend={vi.fn()} onAttach={onAttach} voice={<button>Voice</button>} />);
  const attach = screen.getByRole('button', { name: 'Attach' });
  const voice = screen.getByRole('button', { name: 'Voice' });
  const send = screen.getByRole('button', { name: 'Send' });
  expect(attach.parentElement).toBe(voice.parentElement);
  expect(send.parentElement).toBe(voice.parentElement);
  expect(voice.parentElement?.classList.contains('items-center')).toBe(true);
  fireEvent.click(attach); expect(onAttach).toHaveBeenCalledTimes(1);
  rerender(<ConversationComposer inputRef={inputRef} canExecute={false} labels={{ ...labels, attach: 'Attach' }} onSend={vi.fn()} onAttach={onAttach} />);
  fireEvent.click(screen.getByRole('button', { name: 'Attach' }));
  expect(onAttach).toHaveBeenCalledTimes(1);
});
it('guards readonly and busy sends from both the button and keyboard', () => {
  const onSend = vi.fn(); const inputRef = createRef<HTMLTextAreaElement>();
  const { rerender } = render(<ConversationComposer inputRef={inputRef} canExecute={false} labels={labels} onSend={onSend} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Q' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' }); fireEvent.click(screen.getByLabelText('Send'));
  rerender(<ConversationComposer inputRef={inputRef} canExecute busy labels={labels} onSend={onSend} />);
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
  expect(onSend).not.toHaveBeenCalled();
});
it('does not submit an IME confirmation but permits stopping while input is locked', () => {
  const onSend = vi.fn(); const onStop = vi.fn(); const inputRef = createRef<HTMLTextAreaElement>();
  const { rerender } = render(<ConversationComposer inputRef={inputRef} canExecute labels={labels} onSend={onSend} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Q' } });
  fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter', isComposing: true }); expect(onSend).not.toHaveBeenCalled();
  rerender(<ConversationComposer inputRef={inputRef} canExecute inputDisabled showStop labels={labels} onSend={onSend} onStop={onStop} />);
  fireEvent.click(screen.getByLabelText('Stop')); expect(onStop).toHaveBeenCalledTimes(1);
});
