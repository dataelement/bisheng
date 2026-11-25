import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import * as api from '@/controllers/API/permission';
import type { PermissionGrantAssignee, ResourcePermissionContext } from '@/controllers/API/permission';
import { PermissionListTab } from './PermissionListTab';

vi.mock('@/controllers/API/permission', () => ({
    getGrantablePermissionModelsApi: vi.fn(),
    getMyResourcePermissionsApi: vi.fn(),
    getResourcePermissionGrantsApi: vi.fn(),
    mutateResourceGrantsApi: vi.fn(),
}));

const context: ResourcePermissionContext = {
    mode: 'CUSTOM', parent_type: null, parent_id: null, resource_version: 4,
    catalog_release_id: 6, projection_state: 'CURRENT', can_manage_permission: true,
};
const model = { key: 'owner', name: 'Owner', level: 4 as const, active: true, allow_same_level: true };
const historical: PermissionGrantAssignee = {
    assignee_id: '71', assignee_version: 1, subject: { type: 'user', id: 'None', name: 'user:None' },
    model, source: { type: 'DIRECT', include_children: false, userset_relation: null },
    scope: 'LOCAL', protected: false, editable: true, inherited_from: null,
};

beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.getGrantablePermissionModelsApi).mockResolvedValue([model]);
    vi.mocked(api.getResourcePermissionGrantsApi).mockResolvedValue({
        data: [historical, { ...historical, assignee_id: '72', subject: { type: 'user', id: '897', name: 'Alice' } }],
        page_size: 50, has_more: false, next_cursor: null,
    });
});

it('hides system provenance and historical null-user owners while retaining real-user controls', async () => {
    render(<PermissionListTab resourceType="tool" resourceId="7" context={context} systemPreset />);
    await screen.findByText('Alice');
    expect(screen.queryByTestId('permission-system-preset')).toBeNull();
    expect(screen.queryByText('roster.systemPreset')).toBeNull();
    expect(screen.queryByText('source.system')).toBeNull();
    expect(screen.queryByText('user:None')).toBeNull();
    expect(screen.getByText('Alice')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'grant.remove.71' })).toBeNull();
    expect(screen.getByRole('button', { name: 'grant.remove.72' })).toBeInTheDocument();
    expect(api.mutateResourceGrantsApi).not.toHaveBeenCalled();
});

it.each(['test0528', 'editor'])('hides historical null-user records under model %s', async (modelKey) => {
    vi.mocked(api.getResourcePermissionGrantsApi).mockResolvedValue({
        data: [{ ...historical, model: { ...model, key: modelKey, name: modelKey } }],
        page_size: 50, has_more: false, next_cursor: null,
    });
    render(<PermissionListTab resourceType="tool" resourceId="7" context={context} systemPreset />);
    await screen.findByText('list.emptyForSubject');
    expect(screen.queryByText('user:None')).toBeNull();
    expect(screen.queryByRole('combobox')).toBeNull();
    expect(screen.queryByRole('button', { name: 'grant.remove.71' })).toBeNull();
    expect(api.mutateResourceGrantsApi).not.toHaveBeenCalled();
});

it('shows an empty roster for fresh preset tools without explicit grants', async () => {
    vi.mocked(api.getResourcePermissionGrantsApi).mockResolvedValue({ data: [], page_size: 50, has_more: false, next_cursor: null });
    render(<PermissionListTab resourceType="tool" resourceId="8" context={context} systemPreset />);
    await screen.findByText('list.emptyForSubject');
    expect(screen.queryByTestId('permission-system-preset')).toBeNull();
    expect(screen.queryByText('roster.systemPreset')).toBeNull();
    expect(api.mutateResourceGrantsApi).not.toHaveBeenCalled();
});

it('does not relabel custom-tool user sources as system presets', async () => {
    render(<PermissionListTab resourceType="tool" resourceId="9" context={context} />);
    await screen.findByText('user:None');
    expect(screen.queryByText('roster.systemPreset')).toBeNull();
});

it('keeps system provenance out of department tabs', async () => {
    render(<PermissionListTab resourceType="tool" resourceId="7" context={context} fixedSubjectType="department" systemPreset />);
    await screen.findByText('list.emptyForSubject');
    expect(screen.queryByText('roster.systemPreset')).toBeNull();
});

it('searches real users without synthesizing a system source', async () => {
    render(<PermissionListTab resourceType="tool" resourceId="7" context={context} systemPreset />);
    await screen.findByText('Alice');
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'Alice' } });
    expect(screen.queryByText('roster.systemPreset')).toBeNull();
    expect(screen.getByText('Alice')).toBeInTheDocument();
});

it('locks the business owner source while a directly granted owner remains editable', async () => {
    vi.mocked(api.getResourcePermissionGrantsApi).mockResolvedValue({
        data: [
            { ...historical, subject: { type: 'user', id: '7', name: 'Creator' },
                source: { ...historical.source, type: 'CREATOR' }, protected: true, editable: false },
            { ...historical, assignee_id: '72', subject: { type: 'user', id: '897', name: 'Alice' } },
        ], page_size: 50, has_more: false, next_cursor: null,
    });
    render(<PermissionListTab resourceType="tool" resourceId="7" context={context} />);
    const creator = await screen.findByTestId('permission-assignee-71');
    expect(within(creator).getByLabelText('roster.protected')).toBeInTheDocument();
    expect(within(creator).queryByRole('combobox')).toBeNull();
    expect(within(creator).queryByRole('button')).toBeNull();
    const direct = screen.getByTestId('permission-assignee-72');
    expect(within(direct).getByRole('combobox')).toBeInTheDocument();
    expect(within(direct).getByRole('button', { name: 'grant.remove.72' })).toBeInTheDocument();
});
