import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { WorkflowForm } from './WorkflowForm';
import { normalizeFormFields, validateFormValues } from '../core/workflowForm';
afterEach(cleanup);
it('validates whitespace and empty file arrays while retaining zero and false', () => {
  const fields = normalizeFormFields([{ key: 'q', value: 'Question', type: 'text', required: true }, { key: 'files', value: 'Files', type: 'file', required: true }]);
  expect(validateFormValues(fields, { q: ' ', files: [] }, label => label)).toEqual(['Question', 'Files']);
  expect(validateFormValues(fields, { q: 0, files: ['path'] }, label => label)).toEqual([]);
  expect(validateFormValues(fields, { q: false, files: ['path'] }, label => label)).toEqual([]);
});
it('does not submit readonly forms or submit twice while waiting', () => {
  const onSubmit = vi.fn().mockReturnValue(new Promise(() => undefined));
  const fields = normalizeFormFields([{ key: 'q', value: 'Question', type: 'text', required: true }]);
  const { rerender } = render(<WorkflowForm fields={fields} canExecute={false} submitLabel="Start" requiredMessage={label => label} onSubmit={onSubmit} />);
  fireEvent.click(screen.getByText('Start')); expect(onSubmit).not.toHaveBeenCalled();
  rerender(<WorkflowForm fields={fields} canExecute submitLabel="Start" requiredMessage={label => label} onSubmit={onSubmit} />);
  fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Hi' } });
  fireEvent.click(screen.getByText('Start')); fireEvent.click(screen.getByText('Start'));
  expect(onSubmit).toHaveBeenCalledTimes(1);
  expect(onSubmit).toHaveBeenCalledWith({ q: 'Hi' }, 'Question:Hi\n');
});
it('does not inherit the platform legacy label style', () => {
  const fields = normalizeFormFields([{ key: 'q', value: 'Question', type: 'text' }]);
  const { container } = render(<WorkflowForm fields={fields} canExecute submitLabel="Start" requiredMessage={label => label} onSubmit={vi.fn()} />);
  expect(container.querySelector('.bisheng-label')).toBeNull();
});
it('keeps file upload paths and display names separate through the shared field port', () => {
  const onSubmit = vi.fn();
  const fields = normalizeFormFields([{ key: 'files', value: 'File', type: 'file', required: true }]);
  render(<WorkflowForm fields={fields} canExecute submitLabel="Start" requiredMessage={label => label} onSubmit={onSubmit}
    renderField={({ id, onChange, onFileNameChange }) => <button id={id} onClick={() => { onChange(['/stored/report.pdf']); onFileNameChange('report.pdf'); }}>Upload</button>} />);
  fireEvent.click(screen.getByLabelText(/^File/));
  fireEvent.click(screen.getByRole('button', { name: 'Start' }));
  expect(onSubmit).toHaveBeenCalledWith({ files: ['/stored/report.pdf'] }, 'File:report.pdf\n');
});
