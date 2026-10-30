import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from './Dialog';
import { OGDialog, OGDialogContent, OGDialogTitle } from './OriginalDialog';
import { AlertDialog, AlertDialogContent, AlertDialogTitle, AlertDialogCancel } from './AlertDialog';

jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));
jest.mock('../../utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));

beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState({}, '', '/workspace/skills');
});
afterEach(() => document.documentElement.classList.remove('dark'));

const cases = [
  ['dialog', <Dialog open><DialogContent><DialogTitle>Upload skill</DialogTitle></DialogContent></Dialog>],
  ['original', <OGDialog open><OGDialogContent><OGDialogTitle>Preview</OGDialogTitle></OGDialogContent></OGDialog>],
  ['alert', <AlertDialog open><AlertDialogContent><AlertDialogTitle>Confirm</AlertDialogTitle><AlertDialogCancel>Cancel</AlertDialogCancel></AlertDialogContent></AlertDialog>],
] as const;

it.each(cases)('%s keeps desktop backgrounds transparent in both themes', (_name, content) => {
  window.history.replaceState({}, '', '/workspace/skills?embed=dsh');
  const { rerender } = render(content);
  expect(document.querySelector('[data-state="open"][style*="background"]')).toHaveStyle({ background: 'transparent' });
  document.documentElement.classList.add('dark');
  window.history.replaceState({}, '', '/workspace/knowledge');
  rerender(<React.Fragment>{content}</React.Fragment>);
  expect(document.querySelector('[data-state="open"][style*="background"]')).toHaveStyle({ background: 'transparent' });
});

it.each(cases)('%s uses its normal web presentation in a browser', (_name, content) => {
  render(content);
  expect(document.querySelector('[data-state="open"][style*="background"]')).toBeNull();
  expect(document.querySelector('[data-state="open"][class*="bg-"]')).toBeInTheDocument();
});

it('retains keyboard dismissal, focus containment and return to the trigger', async () => {
  window.history.replaceState({}, '', '/workspace/skills?embed=dsh');
  const user = userEvent.setup();
  render(<Dialog><DialogTrigger>Upload</DialogTrigger><DialogContent><DialogTitle>Upload skill</DialogTitle><input aria-label="Skill file" /><button>Save</button></DialogContent></Dialog>);
  await user.click(screen.getByText('Upload'));
  const dialog = screen.getByRole('dialog');
  expect(dialog).toContainElement(document.activeElement as HTMLElement);
  for (let i = 0; i < 5; i++) {
    await user.tab();
    expect(dialog).toContainElement(document.activeElement as HTMLElement);
  }
  await user.keyboard('{Escape}');
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  expect(screen.getByText('Upload')).toHaveFocus();
});
