import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { RouteDialog } from './RouteDialog';
import { NodeDialog } from './NodeDialog';
import { ApproverUserPicker } from './components/ApproverUserPicker';
import { getUsersApi } from '@/controllers/API/user';
import type { User } from '@/types/api/user';
vi.mock('@/controllers/API/user', () => ({ getRolesApi: vi.fn(async () => []), getUsersApi: vi.fn(async () => ({ data: [], total: 0 })) }));
afterEach(cleanup);

it('appends approvers on scroll without replacing the visible rows', async () => {
    const first = { user_id: 1, user_name: 'First user' } as User;
    const next = { user_id: 2, user_name: 'Next user' } as User;
    let finish!: (page: { data: User[]; total: number }) => void;
    vi.mocked(getUsersApi)
        .mockResolvedValueOnce({ data: [first], total: 2 })
        .mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
    render(<ApproverUserPicker value={[1]} names={['First user']} onChange={vi.fn()} />);

    const row = (await screen.findByRole('checkbox', { name: 'First user' })).closest('label')!;
    const list = row.parentElement!;
    Object.defineProperties(list, {
        clientHeight: { value: 200 },
        scrollHeight: { value: 500 },
        scrollTop: { value: 300, writable: true },
    });
    expect(screen.queryByRole('button', { name: 'subjectSearch.loadMore' })).not.toBeInTheDocument();
    fireEvent.scroll(list);
    expect(getUsersApi).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }), expect.anything());
    expect(row).toBeInTheDocument();
    await act(async () => finish({ data: [next], total: 2 }));
    expect(await screen.findByRole('checkbox', { name: 'Next user' })).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'First user' })).toBeChecked();
    expect(list.scrollTop).toBe(300);
});

it('clears a route condition without leaking the UI sentinel or changing its numeric flow id', async () => {
    const onConfirm = vi.fn();
    await act(async () => { render(<RouteDialog open initial={{ route_name: 'Branch', route_type: 'flow', flow_definition_id: 12, match_config: { field: 'space_type', value: 'public' } }}
        flows={[{ id: 12, flow_name: 'Flow' }]} conditionFields={['space_type']} onClose={vi.fn()} onConfirm={onConfirm} />); });
    fireEvent.click(screen.getByRole('combobox', { name: 'approvalPage.matchConditionHint' }));
    fireEvent.click(screen.getByRole('option', { name: 'approvalPage.noCondition' }));
    fireEvent.click(screen.getByRole('button', { name: 'approvalPage.save' }));
    expect(onConfirm).toHaveBeenCalledWith({ route_name: 'Branch', route_type: 'flow', flow_definition_id: 12, match_config: {} });
});
it('adds an approver through the action menu and preserves the node mode on save', async () => {
    const onConfirm = vi.fn();
    const user = userEvent.setup();
    render(<NodeDialog open initial={{ node_name: 'Review', node_mode: 'or' }} allowedSourceTypes={['department_admin']} onClose={vi.fn()} onConfirm={onConfirm} />);
    await user.click(screen.getByRole('button', { name: 'approvalPage.addApprover' }));
    await user.click(screen.getByRole('menuitem', { name: 'approvalPage.approverSource.department_admin' }));
    fireEvent.click(screen.getByRole('combobox', { name: 'approvalPage.nodeModeLabel' }));
    fireEvent.click(screen.getByRole('option', { name: 'approvalPage.nodeModeAndFull' }));
    fireEvent.click(screen.getByRole('button', { name: 'approvalPage.save' }));
    expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({ node_name: 'Review', node_mode: 'and', approver_config: expect.objectContaining({ sources: [expect.objectContaining({ type: 'department_admin' })] }) }));
});
