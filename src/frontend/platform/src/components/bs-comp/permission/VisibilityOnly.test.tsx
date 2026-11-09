import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { PermissionListTab } from './PermissionListTab';
import * as api from '@/controllers/API/permission';
import type { PermissionGrantAssignee, ResourcePermissionContext } from '@/controllers/API/permission';

vi.mock('@/controllers/API/permission', () => ({ getGrantablePermissionModelsApi: vi.fn(), getMyResourcePermissionsApi: vi.fn(), getResourcePermissionGrantsApi: vi.fn(), mutateResourceGrantsApi: vi.fn() }));
vi.mock('@/components/bs-ui/alertDialog/useConfirm', () => ({ bsConfirm: ({ onOk }: { onOk: (next: () => void) => void }) => onOk(vi.fn()) }));
const context: ResourcePermissionContext = { mode: 'CUSTOM', parent_type: null, parent_id: null, resource_version: 4, catalog_release_id: 6, projection_state: 'CURRENT', can_manage_permission: true };
const model = { key: 'old-use-only', name: 'Original permission name', level: 2 as const, active: true, visibility_only: true };
const row = (id: string, change: Partial<PermissionGrantAssignee> = {}): PermissionGrantAssignee => ({ assignee_id: id, assignee_version: 9, subject: { type: 'user', id: '7', name: 'Same person' }, model, source: { type: 'DIRECT', include_children: false, userset_relation: null }, scope: 'LOCAL', protected: false, editable: true, inherited_from: null, ...change });
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.getGrantablePermissionModelsApi).mockResolvedValue([model]);
  vi.mocked(api.getResourcePermissionGrantsApi).mockResolvedValue({ data: [row('source1'), row('source2')], page_size: 50, has_more: false, next_cursor: null });
  vi.mocked(api.mutateResourceGrantsApi).mockResolvedValue({ resource_version: 5, items: [row('source2')] });
});
it('shows a pure visibility source and revokes precisely one persisted assignee, leaving the other source', async () => {
  render(<PermissionListTab resourceType="knowledge_space" resourceId="9000" context={context} />);
  await screen.findByRole('button', { name: 'grant.remove.source1' });
  expect(screen.getAllByText('roster.visibility_only')).toHaveLength(2);
  fireEvent.click(screen.getByRole('button', { name: 'grant.remove.source1' }));
  await waitFor(() => expect(api.mutateResourceGrantsApi).toHaveBeenCalledOnce());
  expect(vi.mocked(api.mutateResourceGrantsApi).mock.calls[0][2]).toMatchObject({ expected_catalog_release_id: 6, expected_resource_version: 4, changes: [{ op: 'REMOVE', assignee_id: 'source1', expected_assignee_version: 9 }] });
  await waitFor(() => expect(screen.queryByTestId('permission-assignee-source1')).toBeNull());
  expect(screen.getByTestId('permission-assignee-source2')).toBeInTheDocument();
});
it('keeps inactive source revocation while inherited and protected sources cannot be removed', async () => {
  vi.mocked(api.getResourcePermissionGrantsApi).mockResolvedValue({ data: [row('inactive', { model: { ...model, active: false } }), row('inherited', { scope: 'INHERITED' }), row('protected', { protected: true })], page_size: 50, has_more: false, next_cursor: null });
  render(<PermissionListTab resourceType="knowledge_space" resourceId="9000" context={context} />);
  await screen.findByRole('button', { name: 'grant.remove.inactive' });
  expect(screen.queryByRole('button', { name: 'grant.remove.inherited' })).toBeNull();
  expect(screen.queryByRole('button', { name: 'grant.remove.protected' })).toBeNull();
  expect(screen.getByText('roster.inactive_existing_grant')).toBeInTheDocument();
});
it('summary only displays granted actions without inventing use, view_file or rename', async () => {
  vi.mocked(api.getMyResourcePermissionsApi).mockResolvedValue({ mode: 'CUSTOM', actions: ['visible'], sources: [], roster_complete: false });
  render(<PermissionListTab resourceType="knowledge_space" resourceId="9000" context={{ ...context, can_manage_permission: false }} />);
  await screen.findByText('visible');
  expect(screen.queryByText('use')).toBeNull();
  expect(screen.queryByText('view_file')).toBeNull();
  expect(screen.queryByText('rename')).toBeNull();
});
