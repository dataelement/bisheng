import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AllMembersPermission } from './AllMembersPermission'
import { mutateResourceGrantsApi } from '@/controllers/API/permission'
import type { ComponentProps } from 'react'

const switchCallback = vi.hoisted(() => ({ current: undefined as ((enabled: boolean) => unknown) | undefined }))
vi.mock('@bisheng/ui', async importOriginal => {
  const actual = await importOriginal<typeof import('@bisheng/ui')>()
  return {
    ...actual,
    Switch: (props: ComponentProps<typeof actual.Switch>) => {
      switchCallback.current = props.onCheckedChange
      return <actual.Switch {...props} />
    },
  }
})

vi.mock('@/controllers/API/permission', () => ({ mutateResourceGrantsApi: vi.fn() }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (value: Promise<unknown>) => value }))
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (key: string) => key }) }))
const context = {
  mode: 'CUSTOM' as const, parent_type: null, parent_id: null, resource_version: 3,
  catalog_release_id: 4, projection_state: 'CURRENT', can_manage_permission: true,
  tenant_id: '7', all_members_model_key: 'viewer',
  all_members_sources: [{ assignee_id: '9007199254740999', assignee_version: 2 }],
}

const browserCrypto = globalThis.crypto
beforeEach(() => {
  vi.clearAllMocks()
  switchCallback.current = undefined
  // HTTP intranet origins expose getRandomValues but not randomUUID.
  vi.stubGlobal('crypto', { getRandomValues: browserCrypto.getRandomValues.bind(browserCrypto) })
  vi.mocked(mutateResourceGrantsApi).mockResolvedValue({ resource_version: 4, items: [] })
})
afterEach(() => vi.unstubAllGlobals())

describe('all-member authorization', () => {
  it('revokes the persisted public grant with version checks and refreshes', async () => {
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<AllMembersPermission resourceType="tool" resourceId="42" context={context} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('switch', { name: 'allMembers.title' }))
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
    expect(mutateResourceGrantsApi).toHaveBeenCalledWith('tool', '42', expect.objectContaining({
      idempotency_key: expect.stringMatching(/^[0-9a-f]{32}$/),
      expected_resource_version: 3, expected_catalog_release_id: 4,
      changes: [{ op: 'REMOVE', assignee_id: '9007199254740999', expected_assignee_version: 2 }],
    }))
  })

  it('restores all-member visibility with the server-selected model and current tenant', async () => {
    render(<AllMembersPermission resourceType="linsight_skill" resourceId="2" context={{ ...context, all_members_sources: [] }} onChanged={vi.fn()} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(mutateResourceGrantsApi).toHaveBeenCalledWith('linsight_skill', '2', expect.objectContaining({
      idempotency_key: expect.stringMatching(/^[0-9a-f]{32}$/),
      expected_resource_version: 3, expected_catalog_release_id: 4,
      changes: [{ op: 'ADD', model_key: 'viewer', subject: { type: 'tenant', id: '7' } }],
    })))
  })

  it('shows management only for authorized actors', () => {
    render(<AllMembersPermission resourceType="tool" resourceId="42" context={{ ...context, can_manage_permission: false }} onChanged={vi.fn()} />)
    expect(screen.queryByRole('switch')).toBeNull()
    expect(mutateResourceGrantsApi).not.toHaveBeenCalled()
  })

  it('uses the server pure model key without fabricating actions or a model level', async () => {
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<AllMembersPermission resourceType="tool" resourceId="42" context={{ ...context, all_members_sources: [], all_members_model_key: 'original-pure-level-3' }} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
    const body = vi.mocked(mutateResourceGrantsApi).mock.calls[0][2]
    expect(body.changes).toEqual([{ op: 'ADD', model_key: 'original-pure-level-3', subject: { type: 'tenant', id: '7' } }])
    expect(JSON.stringify(body)).not.toMatch(/visibility_only|action_codes|"level"|"use"|"visible"/)
  })

  it('removes precisely the server all-member source identities across a refresh', async () => {
    const tenantSources = [
      { assignee_id: '9007199254740999', assignee_version: 2 },
      { assignee_id: '700', assignee_version: 6 },
    ]
    vi.mocked(mutateResourceGrantsApi).mockResolvedValue({ resource_version: 4, items: [] })
    const onChanged = vi.fn().mockResolvedValue(undefined)
    const view = render(<AllMembersPermission resourceType="tool" resourceId="42" context={{ ...context, all_members_sources: tenantSources }} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
    expect(vi.mocked(mutateResourceGrantsApi).mock.calls[0][2]).toMatchObject({
      expected_resource_version: 3, expected_catalog_release_id: 4,
      changes: [
        { op: 'REMOVE', assignee_id: '9007199254740999', expected_assignee_version: 2 },
        { op: 'REMOVE', assignee_id: '700', expected_assignee_version: 6 },
      ],
    })
    view.rerender(<AllMembersPermission resourceType="tool" resourceId="42" context={{ ...context, resource_version: 4, all_members_sources: [] }} onChanged={onChanged} />)
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
  })

  it('keeps a rejected mutation rejected and does not report a successful refresh', async () => {
    const failure = new Error('projection rejected')
    vi.mocked(mutateResourceGrantsApi).mockRejectedValue(failure)
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<AllMembersPermission resourceType="tool" resourceId="42" context={context} onChanged={onChanged} />)
    expect(switchCallback.current).toBeTypeOf('function')
    await act(async () => {
      await expect(switchCallback.current!(false)).rejects.toBe(failure)
    })
    expect(onChanged).not.toHaveBeenCalled()
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('switch')).toBeEnabled()
  })

  it('locks the switch while a mutation is pending', async () => {
    let resolveMutation!: (value: { resource_version: number, items: [] }) => void
    vi.mocked(mutateResourceGrantsApi).mockReturnValue(new Promise(resolve => { resolveMutation = resolve }))
    const onChanged = vi.fn().mockResolvedValue(undefined)
    render(<AllMembersPermission resourceType="tool" resourceId="42" context={context} onChanged={onChanged} />)
    fireEvent.click(screen.getByRole('switch'))
    expect(screen.getByRole('switch')).toBeDisabled()
    fireEvent.click(screen.getByRole('switch'))
    expect(mutateResourceGrantsApi).toHaveBeenCalledOnce()
    await act(async () => { resolveMutation({ resource_version: 4, items: [] }) })
    expect(onChanged).toHaveBeenCalledOnce()
    expect(screen.getByRole('switch')).toBeEnabled()
  })
})
