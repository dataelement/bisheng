import FilterByUser from '@/components/bs-comp/filterTableDataComponent/FilterByUser';
import { getUsersApi } from '@/controllers/API/user';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('@/controllers/API/user', () => ({ getUsersApi: vi.fn() }));

const api = vi.mocked(getUsersApi);

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom omits PointerEvent, which the real select uses to close after selection.
  vi.stubGlobal('PointerEvent', class extends MouseEvent {
    readonly pointerType = 'mouse';
    readonly pointerId = 1;
  });
});

afterEach(() => vi.unstubAllGlobals());

describe('application usage user filter pagination', () => {
  it('keeps existing users mounted while loading the next page and appends the new users', async () => {
    let resolveNext!: (page: Awaited<ReturnType<typeof getUsersApi>>) => void;
    api.mockResolvedValueOnce({ data: [{ user_id: 1, user_name: 'First user' }], total: 2 } as Awaited<ReturnType<typeof getUsersApi>>);
    api.mockImplementationOnce(() => new Promise(resolve => { resolveNext = resolve; }));
    const onChange = vi.fn();
    render(<FilterByUser value={[]} onChange={onChange} placeholder="Pick user" />);
    await userEvent.setup().click(screen.getByRole('combobox'));
    const first = await screen.findByText('First user');

    // Shared Select requests another page when its popup scrolls to the end.
    fireEvent.scroll(screen.getByRole('listbox').parentElement!);
    await waitFor(() => expect(api).toHaveBeenLastCalledWith(
      { name: '', page: 2, pageSize: 20 }, { signal: expect.any(AbortSignal) },
    ));
    // Removing these rows shrinks the scroll area and sends the browser back to the top.
    expect(first).toBeInTheDocument();

    await act(async () => resolveNext({ data: [{ user_id: 2, user_name: 'Next user' }], total: 2 } as Awaited<ReturnType<typeof getUsersApi>>));
    expect(screen.getByText('First user')).toBe(first);
    await userEvent.setup().click(screen.getByText('Next user'));
    expect(onChange).toHaveBeenCalledWith([{ label: 'Next user', value: 2 }]);
  });
});
