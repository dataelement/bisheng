import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, expect, it, vi } from 'vitest';
import FilterByApp from './FilterByApp';

const getApps = vi.hoisted(() => vi.fn());
vi.mock('@/controllers/API/log', () => ({ getGroupsApi: getApps }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });
function Picker() {
    const [value, setValue] = useState<string[]>([]);
    return <><FilterByApp value={value} onChange={setValue} placeholder="Applications" /><output aria-label="selected">{JSON.stringify(value)}</output></>;
}
it('searches remotely and preserves selected app labels and identifiers across search results', async () => {
    getApps.mockImplementation(({ keyword }: { keyword: string }) => Promise.resolve({ data: keyword ? [{ id: 'b', name: 'Beta' }] : [{ id: 'a', name: 'Alpha' }] }));
    render(<Picker />);
    const input = screen.getByRole('combobox', { name: 'Applications' });
    expect(input.tagName).toBe('INPUT');
    fireEvent.click(input);
    fireEvent.click(await screen.findByRole('option', { name: 'Alpha' }));
    expect(screen.getByLabelText('selected')).toHaveTextContent('["a"]');
    fireEvent.change(screen.getByRole('combobox', { name: 'Applications' }), { target: { value: 'Beta' } });
    await screen.findByRole('option', { name: 'Beta' });
    fireEvent.click(screen.getByRole('option', { name: 'Beta' }));
    expect(screen.getByLabelText('selected')).toHaveTextContent('["a","b"]');
    expect(screen.getAllByText('Alpha', { exact: true })[0]).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole('button', { name: 'sharedUi.remove' })[0]);
    expect(screen.getByLabelText('selected')).toHaveTextContent('["b"]');
    expect(getApps).toHaveBeenLastCalledWith({ keyword: 'Beta', page: 1, page_size: 10 }, expect.objectContaining({ signal: expect.any(AbortSignal) }));
});
it('loads the next page on scroll and stops after the final page', async () => {
    getApps.mockResolvedValueOnce({ data: Array.from({ length: 10 }, (_, i) => ({ id: String(i), name: `App ${i}` })) }).mockResolvedValue({ data: [{ id: 'last', name: 'Last app' }] });
    render(<Picker />);
    fireEvent.click(screen.getByRole('combobox', { name: 'Applications' }));
    await screen.findByRole('option', { name: 'App 0' });
    const panel = screen.getByRole('listbox').parentElement!;
    Object.defineProperties(panel, { scrollHeight: { value: 500 }, clientHeight: { value: 200 }, scrollTop: { value: 300 } });
    fireEvent.scroll(panel);
    await screen.findByRole('option', { name: 'Last app' });
    fireEvent.scroll(panel);
    await waitFor(() => expect(getApps).toHaveBeenCalledTimes(2));
    expect(getApps).toHaveBeenLastCalledWith({ keyword: '', page: 2, page_size: 10 }, expect.anything());
});
