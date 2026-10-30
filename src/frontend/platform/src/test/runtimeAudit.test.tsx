import { cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useRuntimeAudit } from '@/pages/LogPage/runtime/useRuntimeAudit'
import { RuntimeAuditPanel } from '@/pages/LogPage/runtime/RuntimeAuditPanel'
import userEvent from '@testing-library/user-event'

const mock = vi.hoisted(() => ({ records: vi.fn(), candidates: vi.fn(), exportJob: vi.fn(), createExport: vi.fn(), cancelExport: vi.fn() }))
vi.mock('@/controllers/API/runtimeAudit', () => ({ getRuntimeAuditRecords: mock.records, getRuntimeAuditCandidates: mock.candidates, getRuntimeAuditExport: mock.exportJob, createRuntimeAuditExport: mock.createExport, cancelRuntimeAuditExport: mock.cancelExport, downloadRuntimeAuditExport: vi.fn() }))
vi.mock('@/hooks/useAdminScope', () => ({ useAdminScope: () => ({ scope: { scope_tenant_id: null }, loading: false }) }))
vi.mock('@/controllers/API/tenant', () => ({ getTenantsApi: vi.fn().mockResolvedValue({ data: [] }) }))
vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))
vi.mock('@/components/bs-ui/calendar/datePicker', () => ({
  DatePicker: ({ placeholder, onChange }: { placeholder: string; onChange: (date: Date) => void }) =>
    <button onClick={() => onChange(new Date(placeholder.endsWith('start') ? '2026-10-20T09:15:30' : '2026-10-21T18:45:00'))}>{placeholder}</button>,
}))
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
  fireEvent.click(screen.getByRole('radio', { name: 'log.runtime.accessTab' }))
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
  const dialog = screen.getByRole('dialog')
  expect(within(dialog).getByRole('button', { name: 'log.runtime.download' })).toBeVisible()
  await userEvent.click(within(dialog).getAllByRole('button', { name: 'close' })[0])
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  fireEvent.click(screen.getByRole('button', { name: 'log.runtime.export' }))
  expect(await screen.findByRole('dialog')).toBeVisible()
  expect(mock.createExport).toHaveBeenCalledTimes(1)
})

it('renders caller and model metadata while leaving missing tokens unknown and excluding bodies', async () => {
  mock.records.mockResolvedValue({ items: [{ id: 1, actor_kind: 'service_account', actor_name: 'SDK account', model_name: 'Example model', total_tokens: null, prompt: 'PRIVATE_BODY', result: 'success' }], next_cursor: null, snapshot_id: 'selection' })
  render(<RuntimeAuditPanel />, { wrapper })
  expect(await screen.findByText('Example model')).toBeVisible()
  expect(screen.getByText('log.runtime.values.service_account')).toBeVisible()
  expect(screen.getAllByText('log.runtime.unknown').length).toBeGreaterThan(0)
  expect(screen.queryByText('PRIVATE_BODY')).not.toBeInTheDocument()
})

it('keeps a pending export on close and cancels only through the explicit cancel action', async () => {
  const user = userEvent.setup()
  mock.createExport.mockResolvedValue({ export_id: 'pending-job', status: 'pending' })
  mock.exportJob.mockResolvedValue({ export_id: 'pending-job', status: 'running' })
  mock.cancelExport.mockResolvedValue({ export_id: 'pending-job', status: 'expired' })
  render(<RuntimeAuditPanel />, { wrapper })
  await waitFor(() => expect(screen.getByRole('button', { name: 'log.runtime.export' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'log.runtime.export' }))
  await screen.findByRole('button', { name: 'log.runtime.cancel' })
  await user.click(within(screen.getByRole('dialog')).getAllByRole('button', { name: 'close' })[0])
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  expect(mock.cancelExport).not.toHaveBeenCalled()
  await user.click(screen.getByRole('button', { name: 'log.runtime.export' }))
  expect(mock.createExport).toHaveBeenCalledTimes(1)
  mock.exportJob.mockResolvedValue({ export_id: 'pending-job', status: 'expired' })
  await user.click(await screen.findByRole('button', { name: 'log.runtime.cancel' }))
  await waitFor(() => expect(mock.cancelExport).toHaveBeenCalledWith('pending-job', undefined))
  expect(await screen.findByText('log.runtime.status.expired')).toBeVisible()
})

it('shows creation failures inside the dialog and can retry the export', async () => {
  const user = userEvent.setup()
  mock.createExport.mockRejectedValueOnce(new Error('offline')).mockResolvedValue({ export_id: 'retry-job', status: 'pending' })
  mock.exportJob.mockResolvedValue({ export_id: 'retry-job', status: 'ready', final_count: 2 })
  render(<RuntimeAuditPanel />, { wrapper })
  await waitFor(() => expect(screen.getByRole('button', { name: 'log.runtime.export' })).toBeEnabled())
  await user.click(screen.getByRole('button', { name: 'log.runtime.export' }))
  expect(await screen.findByRole('alert')).toHaveTextContent('log.runtime.exportCreateFailed')
  await user.click(screen.getByRole('button', { name: 'build.retry' }))
  expect(await screen.findByRole('button', { name: 'log.runtime.download' })).toBeVisible()
  expect(mock.createExport).toHaveBeenCalledTimes(2)
})

it('renders zoned runtime timestamps in the viewers local time instead of raw UTC', async () => {
  const value = '2026-10-29T03:12:06Z'
  const date = new Date(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  const expected = `${date.getFullYear()}-${pad(date.getMonth()+1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  mock.records.mockResolvedValue({ items: [{ id: 1, create_time: value }], next_cursor: null, snapshot_id: 'selection' })
  render(<RuntimeAuditPanel />, { wrapper })
  expect(await screen.findByText(expected)).toBeVisible()
  expect(screen.queryByText(value)).toBeNull()
})

it('applies custom dates selected through the platform picker and rejects incomplete ranges', async () => {
  const user = userEvent.setup()
  render(<RuntimeAuditPanel />, { wrapper })
  await waitFor(() => expect(mock.records).toHaveBeenCalled())
  await user.click(screen.getByRole('combobox', { name: 'log.runtime.timeRange' }))
  await user.click(screen.getByRole('option', { name: 'log.runtime.custom' }))
  await user.click(screen.getByRole('button', { name: 'log.runtime.apply' }))
  expect(screen.getByRole('alert')).toHaveTextContent('log.runtime.invalidRange')
  await user.click(screen.getByRole('button', { name: 'log.runtime.start' }))
  await user.click(screen.getByRole('button', { name: 'log.runtime.end' }))
  await user.click(screen.getByRole('button', { name: 'log.runtime.apply' }))
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', expect.objectContaining({
    time_range: 'custom', start_time: new Date('2026-10-20T09:15:30').toISOString(), end_time: new Date('2026-10-21T18:45:00').toISOString(),
  }), undefined))
})
