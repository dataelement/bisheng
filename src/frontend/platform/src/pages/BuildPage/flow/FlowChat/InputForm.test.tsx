import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { InputForm } from './InputForm';

vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: {} }) }));
vi.mock('@/components/inputFileComponent', () => ({ default: () => null }));
afterEach(cleanup);

it('retains shared chat layout and submits upstream single/multiple Select values', async () => {
    const onSubmit = vi.fn();
    const { container } = render(<InputForm title="Workflow" logo={<span>Logo</span>} onSubmit={onSubmit} data={{ node_id: 'node', value: [
        { key: 'mode', value: 'Mode', type: 'select', required: true, options: [{ text: '' }, { text: 'First' }, { text: 'Second' }] },
        { key: 'tags', value: 'Tags', type: 'select', multiple: true, options: [{ text: 'Alpha' }, { text: 'Beta' }] },
    ] }} />);
    expect(screen.getByText('Workflow')).toBeInTheDocument();
    expect(container.querySelector('.bisheng-chat-form')).toBeTruthy();
    expect(container.querySelector('.bisheng-label')).toBeNull();
    fireEvent.click(screen.getByRole('combobox', { name: 'Mode' }));
    fireEvent.click(screen.getByRole('option', { name: 'Second' }));
    fireEvent.click(screen.getByRole('combobox', { name: 'Tags' }));
    fireEvent.click(screen.getByRole('option', { name: 'Alpha' }));
    fireEvent.click(screen.getByRole('option', { name: 'Beta' }));
    fireEvent.keyDown(screen.getByRole('combobox', { name: 'Tags' }), { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'report.start' }));
    await waitFor(() => expect(onSubmit).toHaveBeenCalledWith({ mode: 'Second', tags: 'Alpha,Beta' }, 'Mode:Second\nTags:Alpha,Beta\n'));
});
