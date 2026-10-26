import { cleanup, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useRuntimeAudit } from '@/pages/LogPage/runtime/useRuntimeAudit'
import { RuntimeAuditPanel } from '@/pages/LogPage/runtime/RuntimeAuditPanel'

const mock = vi.hoisted(() => ({ records: vi.fn(), candidates: vi.fn(), exportJob: vi.fn(), createExport: vi.fn() }))
vi.mock('@/controllers/API/runtimeAudit', () => ({ getRuntimeAuditRecords: mock.records, getRuntimeAuditCandidates: mock.candidates, getRuntimeAuditExport: mock.exportJob, createRuntimeAuditExport: mock.createExport, cancelRuntimeAuditExport: vi.fn(), downloadRuntimeAuditExport: vi.fn() }))
vi.mock('@/hooks/useAdminScope', () => ({ useAdminScope: () => ({ scope: { scope_tenant_id: null }, loading: false }) }))
vi.mock('@/controllers/API/tenant', () => ({ getTenantsApi: vi.fn().mockResolvedValue({ data: [] }) }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
const wrapper = ({ children }: PropsWithChildren) => <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } })}>{children}</QueryClientProvider>
afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  mock.records.mockResolvedValue({ items: [], next_cursor: null, snapshot_id: 'selection', matched_count: null })
  mock.candidates.mockResolvedValue({ items: [] })
})

it('changes tenant and kind without reusing prior cursor or showing old rows', async () => {
  let resolveOld: (value: unknown) => void = () => undefined
  mock.records.mockResolvedValueOnce({ items: [{ id: 1, app_id: 'old-tenant' }], next_cursor: 'old-cursor', snapshot_id: 'old' })
  const view = renderHook(({ tenant, kind }: { tenant: number; kind: 'model' | 'access' }) => useRuntimeAudit(kind, { time_range: 'all', tenant_id: tenant }, `tenant-${tenant}`), { initialProps: { tenant: 1, kind: 'model' }, wrapper })
  await waitFor(() => expect(view.result.current.query.data?.items[0].app_id).toBe('old-tenant'))
  mock.records.mockImplementationOnce(() => new Promise(resolve => { resolveOld = resolve }))
  view.rerender({ tenant: 2, kind: 'access' })
  expect(view.result.current.query.data).toBeUndefined()
  expect(view.result.current.page).toBe(1)
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('access', expect.objectContaining({ tenant_id: 2 }), undefined))
  resolveOld({ items: [], next_cursor: null, snapshot_id: 'new' })
  await waitFor(() => expect(view.result.current.query.data?.snapshot_id).toBe('new'))
})

it('renders real source rows and distinguishes failed loading from empty records', async () => {
  mock.records.mockRejectedValueOnce(new Error('unavailable'))
  render(<RuntimeAuditPanel />, { wrapper })
  expect(await screen.findByRole('alert')).toHaveTextContent('log.runtime.loadFailed')
  fireEvent.click(screen.getAllByRole('button', { name: 'log.runtime.refresh' })[0])
  await waitFor(() => expect(screen.getByText('log.runtime.empty')).toBeVisible())
  fireEvent.mouseDown(screen.getByRole('tab', { name: 'log.runtime.accessTab' }), { button: 0, ctrlKey: false })
  expect(await screen.findByText('log.runtime.accessHint')).toBeVisible()
})

it('submits full export using the current frozen selection rather than current page rows', async () => {
  mock.createExport.mockResolvedValue({ export_id: 'job', status: 'pending' })
  mock.exportJob.mockResolvedValue({ export_id: 'job', status: 'ready', final_count: 300 })
  render(<RuntimeAuditPanel />, { wrapper })
  await waitFor(() => expect(screen.getByRole('button', { name: 'log.runtime.export' })).toBeEnabled())
  fireEvent.click(screen.getByRole('button', { name: 'log.runtime.export' }))
  await waitFor(() => expect(mock.createExport).toHaveBeenCalledWith('selection', undefined))
  expect(await screen.findByRole('button', { name: 'log.runtime.download' })).toBeVisible()
})

it('renders caller and model metadata while leaving missing tokens unknown and excluding bodies', async () => {
  mock.records.mockResolvedValue({ items: [{ id: 1, actor_kind: 'service_account', actor_name: 'SDK account', model_name: 'Example model', total_tokens: null, prompt: 'PRIVATE_BODY', result: 'success' }], next_cursor: null, snapshot_id: 'selection' })
  render(<RuntimeAuditPanel />, { wrapper })
  expect(await screen.findByText('Example model')).toBeVisible()
  expect(screen.getByText('log.runtime.values.service_account')).toBeVisible()
  expect(screen.getAllByText('log.runtime.unknown').length).toBeGreaterThan(0)
  expect(screen.queryByText('PRIVATE_BODY')).not.toBeInTheDocument()
})
