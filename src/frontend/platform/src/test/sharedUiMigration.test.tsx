import React, { createRef } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import userEvent from '@testing-library/user-event';
import { Button, LoadButton } from '@/components/bs-ui/button';
import { Input, InputList, NonNegativeInput, PassInput, PasswordInput, Textarea } from '@/components/bs-ui/input';
import { Toaster } from '@/components/bs-ui/toast';
import { message, toast } from '@/components/bs-ui/toast/use-toast';

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('shared UI compatibility', () => {
  it('blocks repeat submissions while a standard button is loading', () => {
    const onClick = vi.fn();
    render(<Button loading onClick={onClick}>Save</Button>);
    const button = screen.getByRole('button', { name: 'Save' });
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });

  it('keeps the legacy loading button disabled and forwards its ref', () => {
    const ref = createRef<HTMLButtonElement>();
    render(<LoadButton ref={ref} loading>Save</LoadButton>);
    expect(ref.current).toBeDisabled();
    expect(ref.current).toHaveAttribute('aria-busy', 'true');
  });

  it('reflects an externally reset numeric value of zero', () => {
    const { rerender } = render(<Input aria-label="Quota" type="number" value={5} onChange={() => {}} />);
    rerender(<Input aria-label="Quota" type="number" value={0} onChange={() => {}} />);
    expect(screen.getByRole('spinbutton')).toHaveValue(0);
  });

  it('preserves numeric bounds and allows fractional input below one', () => {
    const onChange = vi.fn();
    render(<Input aria-label="Size" type="number" min={0.1} max={2} defaultValue="" onChange={onChange} />);
    const input = screen.getByRole('spinbutton');
    fireEvent.change(input, { target: { value: '0' } });
    fireEvent.change(input, { target: { value: '0.5' } });
    expect(input).toHaveValue(0.5);
    fireEvent.change(input, { target: { value: '3' } });
    expect(input).toHaveValue(0.5);
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it('keeps native length limits and form refs for input and textarea', () => {
    const ref = createRef<HTMLInputElement>();
    render(<><Input ref={ref} aria-label="Name" maxLength={4} /><Textarea aria-label="Notes" maxLength={8} /></>);
    expect(ref.current).toHaveAttribute('maxlength', '4');
    expect(screen.getByRole('textbox', { name: 'Notes' })).toHaveAttribute('maxlength', '8');
  });

  it('lets native form reset restore an uncontrolled input default', () => {
    render(<form aria-label="Settings"><Input aria-label="Name" defaultValue="Original" /></form>);
    const input = screen.getByRole('textbox', { name: 'Name' });
    fireEvent.change(input, { target: { value: 'Edited' } });
    act(() => (screen.getByRole('form') as HTMLFormElement).reset());
    expect(input).toHaveValue('Original');
  });

  it('applies composer sizing to the textarea that callers resize through its ref', () => {
    const ref = createRef<HTMLTextAreaElement>();
    render(<><style>{'.composer-field { max-height: 200px; resize: none; }'}</style>
      <Textarea ref={ref} aria-label="Message" className="composer-field" /></>);
    ref.current!.style.height = '400px';
    expect(getComputedStyle(ref.current!).maxHeight).toBe('200px');
    expect(getComputedStyle(ref.current!).resize).toBe('none');
  });

  it('toggles password visibility without losing the value or field ref', () => {
    const ref = createRef<HTMLInputElement>();
    render(<PasswordInput ref={ref} aria-label="Secret" defaultValue="secret" />);
    const input = screen.getByLabelText('Secret');
    expect(input).toHaveAttribute('type', 'password');
    fireEvent.click(screen.getByRole('button'));
    expect(input).toHaveAttribute('type', 'text');
    expect(input).toHaveValue('secret');
    expect(ref.current).toBe(input);
  });

  it('allows file selection without attempting to control the file path', async () => {
    const onChange = vi.fn();
    render(<Input type="file" aria-label="Plugin" onChange={onChange} />);
    const file = new File(['plugin'], 'plugin.zip', { type: 'application/zip' });
    const input = screen.getByLabelText('Plugin') as HTMLInputElement;
    await userEvent.upload(input, file);
    expect(input.files?.[0]).toBe(file);
    expect(onChange).toHaveBeenCalledTimes(1);
  });

  it('keeps secret editing and paste on the real field value', async () => {
    const onChange = vi.fn();
    render(<PassInput aria-label="API key" defaultValue="old" onChange={onChange} />);
    const input = screen.getByLabelText('API key');
    await userEvent.clear(input);
    await userEvent.type(input, 'new-key');
    expect(input).toHaveValue('new-key');
    expect(onChange.mock.calls.at(-1)![0].target.value).toBe('new-key');
  });

  it('withholds an invalid numeric value and restores the default on empty blur', () => {
    const onValueChange = vi.fn();
    render(<NonNegativeInput aria-label="Limit" min={1} max={4} defaultValue={2} onValueChange={onValueChange} />);
    const input = screen.getByRole('textbox', { name: 'Limit' });
    fireEvent.change(input, { target: { value: '8' } });
    expect(input).toHaveValue('8');
    expect(input).toHaveAttribute('aria-invalid', 'true');
    expect(onValueChange).not.toHaveBeenCalled();
    fireEvent.change(input, { target: { value: '' } });
    fireEvent.blur(input);
    expect(input).toHaveValue('2');
    expect(onValueChange).toHaveBeenLastCalledWith(2);
  });

  it('preserves dictionary row identifiers when editing a list', () => {
    const onChange = vi.fn();
    render(<InputList dict value={[{ key: 'preset-1', value: 'First' }]} onChange={onChange} />);
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Changed' } });
    expect(onChange.mock.calls[0][0][0]).toEqual({ key: 'preset-1', value: 'Changed' });
    expect(onChange.mock.calls[0][1]).toEqual({ action: 'u', id: 'preset-1', value: 'Changed' });
  });

  it('updates a notice in place and preserves its dismiss handle', () => {
    vi.useFakeTimers();
    render(<Toaster />);
    let handle: ReturnType<typeof toast>;
    act(() => { handle = toast({ title: 'Import job', description: 'Queued', duration: 0 }); });
    act(() => handle!.update({ description: ['Finished', 'All rows imported'], variant: 'success' }));
    expect(screen.queryByText('Queued')).not.toBeInTheDocument();
    expect(screen.getAllByText('Import job')).toHaveLength(1);
    act(() => handle!.dismiss());
    act(() => vi.advanceTimersByTime(300));
    expect(screen.queryByText('Import job')).not.toBeInTheDocument();
  });

  it('deduplicates messages and preserves separate right-side notifications', () => {
    vi.useFakeTimers();
    render(<Toaster />);
    let notice: ReturnType<typeof toast>;
    let first: ReturnType<typeof message>;
    let second: ReturnType<typeof message>;
    act(() => {
      first = message({ description: 'Saved', variant: 'success' });
      second = message({ description: 'Saved', variant: 'success' });
      notice = toast({ title: 'Import', description: ['Row 1 failed', 'Row 2 failed'], variant: 'error' });
    });
    expect(first!.id).toBe(second!.id);
    // The shared container also announces the latest message in a live region.
    expect(screen.getAllByText('Saved', { selector: 'span' })).toHaveLength(1);
    expect(screen.getByText('Import')).toBeInTheDocument();
    expect(screen.getByText(/Row 1 failed/)).toHaveTextContent('Row 2 failed');
    act(() => notice!.dismiss());
    act(() => vi.advanceTimersByTime(300));
    expect(screen.queryByText('Import')).not.toBeInTheDocument();
    act(() => first!.dismiss());
    act(() => vi.runOnlyPendingTimers());
  });
});
