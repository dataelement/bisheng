import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { RouteDialog } from './RouteDialog';
import { NodeDialog } from './NodeDialog';
vi.mock('@/controllers/API/user', () => ({ getRolesApi: vi.fn(async () => []), getUsersApi: vi.fn(async () => ({ data: [], total: 0 })) }));
afterEach(cleanup);

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
