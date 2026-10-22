import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { PromptDialog } from './KnowledgeModel';

vi.mock('./WorkbenchModel', () => ({ defalutPrompt: 'default' }));
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }));
afterEach(cleanup);

it('keeps a failed prompt draft open and changes the accepted value only after a successful retry', async () => {
    let rejectSave: (reason: unknown) => void = () => undefined;
    const onSave = vi.fn().mockImplementationOnce(() => new Promise<void>((_resolve, reject) => { rejectSave = reject; })).mockResolvedValueOnce(undefined);
    const onChange = vi.fn();
    render(<PromptDialog value="accepted prompt" onChange={onChange} onSave={onSave} label="Prompt"><span>Edit prompt</span></PromptDialog>);
    fireEvent.click(screen.getByRole('button', { name: 'Edit prompt' }));
    fireEvent.change(await screen.findByRole('textbox'), { target: { value: 'edited draft' } });
    fireEvent.click(screen.getByRole('button', { name: 'model.save' }));
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('edited draft'));
    expect(screen.getByRole('button', { name: 'model.save' })).toBeDisabled();
    expect(onChange).not.toHaveBeenCalled();
    await act(async () => { rejectSave(new Error('save unavailable')); });
    expect(await screen.findByRole('textbox')).toHaveValue('edited draft');
    expect(screen.getByRole('button', { name: 'model.save' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'model.save' }));
    await waitFor(() => expect(onChange).toHaveBeenCalledWith('edited draft'));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
