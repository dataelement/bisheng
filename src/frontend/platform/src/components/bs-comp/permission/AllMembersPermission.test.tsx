import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { AllMembersPermission } from './AllMembersPermission'
import { mutateResourceGrantsApi } from '@/controllers/API/permission'

vi.mock('@/controllers/API/permission', () => ({ mutateResourceGrantsApi: vi.fn() }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (value: Promise<unknown>) => value }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const context = {
  mode: 'CUSTOM' as const, parent_type: null, parent_id: null, resource_version: 3,
  catalog_release_id: 4, projection_state: 'CURRENT', can_manage_permission: true,
  tenant_id: '7', all_members_model_key: 'viewer',
  all_members_sources: [{ assignee_id: '9007199254740999', assignee_version: 2 }],
}

beforeEach(() => { vi.clearAllMocks(); vi.mocked(mutateResourceGrantsApi).mockResolvedValue({ resource_version: 4, items: [] }) })

describe('all-member authorization', () => {
  it('revokes the persisted public grant with version checks and refreshes', async () => {
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<AllMembersPermission resourceType="tool" resourceId="42" context={context} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('switch', { name: 'allMembers.title' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
    expect(mutateResourceGrantsApi).toHaveBeenCalledWith('tool', '42', expect.objectContaining({
      expected_resource_version: 3, expected_catalog_release_id: 4,
      changes: [{ op: 'REMOVE', assignee_id: '9007199254740999', expected_assignee_version: 2 }],
    }))
  })

  it('restores all-member use with the server-selected model and current tenant', async () => {
    render(<AllMembersPermission resourceType="linsight_skill" resourceId="2" context={{ ...context, all_members_sources: [] }} onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(mutateResourceGrantsApi).toHaveBeenCalledWith('linsight_skill', '2', expect.objectContaining({
      changes: [{ op: 'ADD', model_key: 'viewer', subject: { type: 'tenant', id: '7' } }],
    })))
  })

  it('shows management only for authorized actors', () => {
    render(<AllMembersPermission resourceType="tool" resourceId="42" context={{ ...context, can_manage_permission: false }} onChanged={vi.fn()} />)
    expect(screen.queryByRole('switch')).toBeNull()
  })
})
