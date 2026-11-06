import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { HostedAppDetail, HostedAppInstance } from '@/controllers/API/hostedApp'
import { PublishTab } from '@/pages/BuildPage/hostedApp/tabs/PublishTab'
import { CandidateFilter } from '@/pages/LogPage/runtime/RuntimeAuditPanel'

const mock = vi.hoisted(() => ({ candidates: vi.fn() }))
vi.mock('@/controllers/API/runtimeAudit', () => ({ getRuntimeAuditCandidates: mock.candidates }))
vi.mock('@/pages/BuildPage/useHostedAppActions', () => ({ useHostedAppActions: () => ({}) }))
vi.mock('@/utils', () => ({ copyText: vi.fn() }))
vi.mock('@/contexts/userContext', async () => ({ userContext: (await import('react')).createContext({ user: {} }) }))
vi.mock('@/contexts/locationContext', async () => ({ locationContext: (await import('react')).createContext({ appConfig: {} }) }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))

const app: HostedAppDetail = { app_id: 'a', slug: 'app', name: 'App', description: null, logo: null, owner_user_id: 9, tenant_id: 60, current_version_id: 'v1', pending_version_id: null, create_time: null, update_time: null, state: 'online', allowed_actions: [], entry_url: '/apps/app' }
const instance = { phase: 'running', health: 'healthy', restart_count: 0, started_at: '2026-11-02T01:02:03Z', observation_state: 'current' } as HostedAppInstance
const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } })}>{children}</QueryClientProvider>
afterEach(cleanup)
beforeEach(() => { vi.clearAllMocks(); mock.candidates.mockResolvedValue({ items: [], has_more: false }) })

it('preserves real zero but refuses stale or invalid runtime facts', () => {
  const view = render(<PublishTab app={app} instance={instance} onChanged={vi.fn()} />)
  expect(screen.getByText('0')).toBeVisible()
  view.rerender(<PublishTab app={app} instance={{ ...instance, observation_state: 'execution_missing', restart_count: null }} onChanged={vi.fn()} />)
  expect(screen.queryByText('0')).toBeNull()
  expect(screen.getByText('f115.runtime.executionMissing')).toBeVisible()
  view.rerender(<PublishTab app={app} instance={{ ...instance, health: 'private-native-value', started_at: 'invalid', restart_count: null }} onChanged={vi.fn()} />)
  expect(screen.queryByText('private-native-value')).toBeNull()
  expect(screen.queryByText('invalid')).toBeNull()
  expect(screen.getAllByText('f115.runtime.unknown').length).toBeGreaterThan(0)
})

it('distinguishes empty candidates from failure and retries without fabricated users', async () => {
  const user = userEvent.setup()
  mock.candidates.mockRejectedValueOnce(new Error('offline'))
  render(<CandidateFilter kind="model" dimension="visitor" filters={{ time_range: 'all' }} scopeKey="60" onChange={vi.fn()} />, { wrapper })
  expect(await screen.findByRole('alert')).toHaveTextContent('f115.audit.candidatesFailed')
  await user.click(screen.getByRole('button', { name: 'f115.audit.retry' }))
  await waitFor(() => expect(screen.queryByRole('alert')).toBeNull())
  await user.click(screen.getByRole('combobox'))
  expect(await screen.findByText('f115.audit.noVisitors')).toBeVisible()
})

it('does not show old-tenant candidates while the new range is loading', async () => {
  mock.candidates.mockResolvedValue({ items: [{ id: '9', label: 'Alice' }], has_more: false })
  const view = render(<CandidateFilter kind="model" dimension="visitor" filters={{ time_range: 'all' }} scopeKey="60" onChange={vi.fn()} />, { wrapper })
  await waitFor(() => expect(mock.candidates).toHaveBeenCalled())
  mock.candidates.mockReturnValue(new Promise(() => undefined))
  view.rerender(<CandidateFilter kind="model" dimension="visitor" filters={{ time_range: 'all' }} scopeKey="61" onChange={vi.fn()} />)
  expect(screen.queryByText('Alice')).toBeNull()
})
