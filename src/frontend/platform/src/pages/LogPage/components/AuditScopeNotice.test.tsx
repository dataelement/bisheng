import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { AuditScopeNotice } from './AuditScopeNotice'

const mock = vi.hoisted(() => ({ scope: vi.fn() }))
vi.mock('@bisheng/ui', () => ({
  Alert: ({ description }: { description: string }) => <div>{description}</div>,
}))
vi.mock('@/controllers/API/log', () => ({ getAuditScopeApi: mock.scope }))

it('shows the current tenant and organization range above the audit tabs', async () => {
  mock.scope.mockResolvedValue({
    tenant_id: 60,
    tenant_name: 'child-tenant',
    unrestricted_organization: false,
    organizations: [{ name: 'research', includes_descendants: true }],
  })
  render(<AuditScopeNotice />)
  expect(await screen.findByText('log.scope.summary')).toBeVisible()
})

it('keeps the page usable when the range cannot be loaded', async () => {
  mock.scope.mockRejectedValue(new Error('offline'))
  render(<AuditScopeNotice />)
  expect(await screen.findByText('log.scope.loadFailed')).toBeVisible()
})
