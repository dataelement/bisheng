import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkflowFileField } from './WorkflowFileField';
afterEach(cleanup);
it('keeps the filename and icon in one clickable field and shows the empty placeholder', () => {
  const onClick = vi.fn();
  const { rerender } = render(<WorkflowFileField placeholder="No file" onClick={onClick} />);
  const field = screen.getByRole('button', { name: 'No file' });
  expect(field.querySelector('svg')).toBeTruthy();
  fireEvent.click(field.querySelector('svg')!);
  expect(onClick).toHaveBeenCalledTimes(1);
  rerender(<WorkflowFileField value="report.pdf" placeholder="No file" onClick={onClick} />);
  expect(screen.getByRole('button', { name: 'report.pdf' })).toBeTruthy();
  expect(screen.queryByText('No file')).toBeNull();
});
it('does not open a picker while disabled or uploading', () => {
  const onClick = vi.fn();
  const { rerender } = render(<WorkflowFileField disabled placeholder="No file" onClick={onClick} />);
  fireEvent.click(screen.getByRole('button'));
  rerender(<WorkflowFileField loading placeholder="No file" onClick={onClick} />);
  fireEvent.click(screen.getByRole('button'));
  expect(onClick).not.toHaveBeenCalled();
});
