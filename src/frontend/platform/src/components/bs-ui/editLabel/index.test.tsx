import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import EditLabel from './index';

vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
afterEach(cleanup);

it('keeps a rejected finetune name draft and waits for retry success before leaving edit mode', async () => {
    const onChange = vi.fn().mockRejectedValueOnce(new Error('Rename failed')).mockResolvedValue(undefined);
    render(<EditLabel str="Model" rule={[]} onChange={onChange}>{(name: string) => <span>{name}</span>}</EditLabel>);
    fireEvent.click(screen.getByRole('button'));
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Draft model' } });
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('textbox')).toHaveValue('Draft model');
    await waitFor(() => expect(screen.getByRole('textbox')).toBeEnabled());
    fireEvent.keyDown(screen.getByRole('textbox'), { key: 'Enter' });
    await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument());
    expect(onChange).toHaveBeenLastCalledWith('Draft model');
});

it('does not resubmit while a rename is pending', async () => {
    let complete!: () => void;
    const onChange = vi.fn(() => new Promise<void>(resolve => { complete = resolve; }));
    render(<EditLabel str="Model" rule={[]} onChange={onChange}>{(name: string) => <span>{name}</span>}</EditLabel>);
    fireEvent.click(screen.getByRole('button'));
    const input = screen.getByRole('textbox');
    fireEvent.keyDown(input, { key: 'Enter' });
    fireEvent.blur(input);
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(input).toBeDisabled();
    expect(onChange).toHaveBeenCalledTimes(1);
    complete();
    await waitFor(() => expect(screen.queryByRole('textbox')).not.toBeInTheDocument());
});
