import { RouteDialog } from '@/pages/ApprovalPage/RouteDialog';
import { render, screen, selectOption, waitFor } from '@/test/test-utils';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

vi.mock('@/controllers/API/user', () => ({ getRolesApi: vi.fn(async () => []) }));

const initial = { route_name: 'Published app approval', route_type: 'pass' };

describe('mandatory approval after the page split', () => {
  it('converts a stored pass route to flow and prevents saving without a flow', async () => {
    const onConfirm = vi.fn();
    render(<RouteDialog open initial={initial} flows={[]} conditionFields={[]} allowPassRoute={false}
      onClose={vi.fn()} onConfirm={onConfirm} />);
    await userEvent.click(screen.getByLabelText('approvalPage.routeTypeLabel'));
    expect(await screen.findByRole('option', { name: 'approvalPage.routeTypeFlowFull' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'approvalPage.routeTypePassFull' })).toBeNull();
    await userEvent.keyboard('{Escape}');
    expect(screen.getByText('approvalPage.routeTypeMandatoryHint')).toBeInTheDocument();
    const save = screen.getByRole('button', { name: 'approvalPage.save' });
    expect(save).toBeDisabled();
    await userEvent.click(save);
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('keeps automatic approval available for the other existing scenarios', async () => {
    render(<RouteDialog open initial={initial} flows={[]} conditionFields={[]}
      onClose={vi.fn()} onConfirm={vi.fn()} />);
    await userEvent.click(screen.getByLabelText('approvalPage.routeTypeLabel'));
    expect(await screen.findByRole('option', { name: 'approvalPage.routeTypePassFull' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'approvalPage.save' })).toBeEnabled();
  });

  it('submits a flow route for a mandatory scenario after selecting a flow', async () => {
    const onConfirm = vi.fn();
    render(<RouteDialog open initial={initial} flows={[{ id: 12, flow_name: 'Reviewed flow', flow_code: 'reviewed' }]}
      conditionFields={[]} allowPassRoute={false} onClose={vi.fn()} onConfirm={onConfirm} />);
    await selectOption('approvalPage.bindFlow', 'Reviewed flow');
    await userEvent.click(screen.getByRole('button', { name: 'approvalPage.save' }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith({
      route_name: initial.route_name, route_type: 'flow', flow_definition_id: 12, match_config: {},
    }));
  });
});
