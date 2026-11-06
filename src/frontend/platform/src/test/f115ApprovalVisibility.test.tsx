import { act, cleanup, render, renderHook, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { CurrentAppVisibility } from '@/pages/ApprovalPage/CurrentAppVisibility'
import { useApprovalExceptions } from '@/pages/ApprovalPage/useApprovalExceptions'

const mock = vi.hoisted(() => ({ detail: vi.fn() }))
vi.mock('@/controllers/API/approval', () => ({ getApprovalInstanceDetailForAdminApi: mock.detail }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('keeps unavailable scope distinct from owner-only and exposes a refresh action', () => {
  const refresh = vi.fn()
  const view = render(<CurrentAppVisibility value={{ state: 'unavailable', owner_only: null, subjects: [] }} onRefresh={refresh} />)
  expect(screen.getByText('f115.visibility.unavailable')).toBeVisible()
  expect(screen.queryByText('f115.visibility.ownerOnly')).toBeNull()
  view.rerender(<CurrentAppVisibility value={{ state: 'available', owner_only: true, subjects: [{ type: 'user', id: '9', name: 'Owner' }] }} onRefresh={refresh} />)
  expect(screen.getByText('f115.visibility.ownerOnly')).toBeVisible()
  expect(screen.getByText(/Owner/)).toBeVisible()
})

it('reloads current authorization every time exception progress is reopened', async () => {
  mock.detail.mockResolvedValue({ instance_id: 1, current_visibility: { state: 'available', subjects: [] } })
  const { result } = renderHook(() => useApprovalExceptions({ loadPage: vi.fn() }))
  const item = { id: 3, instance_id: 1, exception_type: 'approver_empty' }
  await act(() => result.current.toggleExceptionProgress(item))
  await act(() => result.current.toggleExceptionProgress(item))
  await act(() => result.current.toggleExceptionProgress(item))
  expect(mock.detail).toHaveBeenCalledTimes(2)
})
