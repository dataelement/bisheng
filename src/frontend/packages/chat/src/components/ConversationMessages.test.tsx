import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { normalizeHistory } from '../core/normalizeHistory';
import { ConversationMessages } from './ConversationMessages';
import { SuggestedQuestions } from './SuggestedQuestions';
afterEach(cleanup);
it('keeps greeting actions at the right of their hover group like the client baseline', () => {
  render(<ConversationMessages messages={normalizeHistory([{ category: 'guide_word', message: 'Welcome' }], { mode: 'workflow', sessionKey: 'a' })}
    canExecute labels={{ confirm: 'Confirm', confirmed: 'Confirmed', thinking: 'Thinking', completed: 'Done' }}
    slots={{ title: () => 'Assistant', content: text => text, footer: () => <button>Play</button> }} />);
  const footer = screen.getByRole('button', { name: 'Play' }).parentElement;
  expect(footer?.classList.contains('justify-end')).toBe(true);
  expect(footer?.classList.contains('pr-4')).toBe(true);
  expect(footer?.classList.contains('fine-pointer:opacity-0')).toBe(true);
  expect(footer?.closest('.group')).toBeTruthy();
});
it('renders client-style suggested questions in normal message flow and guards readonly clicks', () => {
  const onSelect = vi.fn();
  const { rerender, container } = render(<SuggestedQuestions questions={['First', 'Second']} canExecute onSelect={onSelect} />);
  expect(container.querySelector('.absolute')).toBeNull();
  fireEvent.click(screen.getByRole('button', { name: 'First' }));
  expect(onSelect).toHaveBeenCalledWith('First');
  rerender(<SuggestedQuestions questions={['First']} canExecute={false} onSelect={onSelect} />);
  expect(screen.queryByRole('button', { name: 'First' })).toBeNull();
});
