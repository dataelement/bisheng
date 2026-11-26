import { ApproverUserPicker } from '@/pages/ApprovalPage/components/ApproverUserPicker';
import { getExceptionApproverCandidatesApi, type ApprovalApproverCandidate } from '@/controllers/API/approval';
import { getUsersApi } from '@/controllers/API/user';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';

vi.mock('@/controllers/API/approval', () => ({ getExceptionApproverCandidatesApi: vi.fn() }));
vi.mock('@/controllers/API/user', () => ({ getUsersApi: vi.fn() }));
const candidates = vi.mocked(getExceptionApproverCandidatesApi);
const users = vi.mocked(getUsersApi);
const chosen = vi.fn();

function Picker({ exceptionId }: { exceptionId?: number }) {
    const [value, setValue] = useState<number[]>([]);
    const [names, setNames] = useState<string[]>([]);
    return <ApproverUserPicker exceptionId={exceptionId} value={value} names={names} onChange={(ids, labels) => {
        chosen(ids); setValue(ids); setNames(labels);
    }} />;
}

beforeEach(() => {
    vi.clearAllMocks();
    candidates.mockResolvedValue({ data: [{ user_id: 895, user_name: 'gzx110', external_id: 'gzx110' }], total: 1 });
    users.mockResolvedValue({ data: [], total: 0 });
});
afterEach(cleanup);

it('requests only qualified people for this exception and selects the numeric user ID', async () => {
    render(<Picker exceptionId={79} />);
    await screen.findByText('gzx110', { selector: 'span.text-sm' });
    expect(candidates).toHaveBeenCalledWith(79, '', 1, expect.any(AbortSignal));
    expect(users).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('checkbox'));
    expect(chosen).toHaveBeenLastCalledWith([895]);
});

it('does not fall back to the generic directory when candidate loading fails', async () => {
    candidates.mockRejectedValue(new Error('unavailable'));
    render(<Picker exceptionId={79} />);
    await waitFor(() => expect(screen.getByText('subjectSearch.failed')).toBeInTheDocument());
    expect(users).not.toHaveBeenCalled();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
});

it('retires another exception response when the exception changes', async () => {
    let finish!: (result: { data: ApprovalApproverCandidate[]; total: number }) => void;
    candidates.mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    const page = render(<Picker exceptionId={79} />);
    await waitFor(() => expect(candidates).toHaveBeenCalledWith(79, '', 1, expect.any(AbortSignal)));
    page.rerender(<Picker exceptionId={80} />);
    await screen.findByRole('checkbox');
    await act(async () => { finish({ data: [{ user_id: 1, user_name: 'stale person' }], total: 1 }); });
    expect(screen.queryByText('stale person')).not.toBeInTheDocument();
    expect(candidates).toHaveBeenLastCalledWith(80, '', 1, expect.any(AbortSignal));
});

it('keeps a proven self-review exception exclusive in either selection order', async () => {
    candidates.mockResolvedValue({ data: [
        { user_id: 868, user_name: 'sole administrator', exclusive: true },
        { user_id: 895, user_name: 'other reviewer', exclusive: false },
    ], total: 2 });
    render(<Picker exceptionId={79} />);
    await screen.findByText('sole administrator');
    const boxes = screen.getAllByRole('checkbox');
    fireEvent.click(boxes[0]);
    expect(chosen).toHaveBeenLastCalledWith([868]);
    fireEvent.click(boxes[1]);
    expect(chosen).toHaveBeenLastCalledWith([895]);
    fireEvent.click(boxes[0]);
    expect(chosen).toHaveBeenLastCalledWith([868]);
});

it('keeps the flow-node configuration picker on its original source', async () => {
    render(<Picker />);
    await waitFor(() => expect(users).toHaveBeenCalled());
    expect(candidates).not.toHaveBeenCalled();
});

it('clears selections and reloads candidates after management tenant changes', async () => {
    render(<Picker exceptionId={79} />);
    fireEvent.click(await screen.findByRole('checkbox'));
    expect(chosen).toHaveBeenLastCalledWith([895]);
    await act(async () => { window.dispatchEvent(new Event('bisheng:management-scope-changed')); });
    expect(chosen).toHaveBeenLastCalledWith([]);
    await waitFor(() => expect(candidates).toHaveBeenCalledTimes(2));
});
