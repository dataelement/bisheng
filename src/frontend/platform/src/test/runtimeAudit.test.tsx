import { cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { PropsWithChildren } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { useRuntimeAudit } from '@/pages/LogPage/runtime/useRuntimeAudit'
import { RuntimeAuditPanel } from '@/pages/LogPage/runtime/RuntimeAuditPanel'
import userEvent from '@testing-library/user-event'

const mock = vi.hoisted(() => ({ records: vi.fn(), candidates: vi.fn(), exportJob: vi.fn(), createExport: vi.fn(), cancelExport: vi.fn(), departments: vi.fn() }))
vi.mock('@/controllers/API/log', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/controllers/API/log')>()), getAuditDepartmentsApi: mock.departments }))
vi.mock('@/controllers/API/runtimeAudit', async (importOriginal) => ({ ...(await importOriginal<typeof import('@/controllers/API/runtimeAudit')>()), getRuntimeAuditRecords: mock.records, getRuntimeAuditCandidates: mock.candidates, getRuntimeAuditExport: mock.exportJob, createRuntimeAuditExport: mock.createExport, cancelRuntimeAuditExport: mock.cancelExport, downloadRuntimeAuditExport: vi.fn() }))
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
  fireEvent.click(screen.getByRole('button', { name: 'log.runtime.refresh' }))
  await waitFor(() => expect(screen.getByText('log.emptyTitle')).toBeVisible())
  fireEvent.click(screen.getByRole('radio', { name: 'log.runtime.accessTab' }))
  expect(await screen.findByText('log.runtime.accessHint')).toBeVisible()
})

it('reloads the first page on every search without clearing an unchanged visitor filter', async () => {
  const user = userEvent.setup()
  mock.candidates.mockResolvedValue({ items: [{ id: '7', label: 'Audit visitor' }] })
  mock.records.mockResolvedValue({ items: [], next_cursor: 'page-two', snapshot_id: 'initial' })
  render(<RuntimeAuditPanel />, { wrapper })
  await user.click(screen.getByRole('combobox', { name: 'log.runtime.visitor' }))
  await user.click(await screen.findByRole('option', { name: 'Audit visitor' }))
  const expectedFilters = expect.objectContaining({ time_range: 'recent7d', visitor_id: 7 })
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', expectedFilters, undefined))

  const next = screen.getByRole('button', { name: 'log.runtime.next' })
  await waitFor(() => expect(next).toBeEnabled())
  await user.click(next)
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', expectedFilters, 'page-two'))

  const search = screen.getByRole('button', { name: 'log.runtime.apply' })
  mock.records.mockResolvedValueOnce({ items: [{ id: 1, model_name: 'Fresh record' }], next_cursor: null, snapshot_id: 'fresh' })
  await user.click(search)
  expect(await screen.findByText('Fresh record')).toBeVisible()
  expect(mock.records).toHaveBeenLastCalledWith('model', expectedFilters, undefined)
  expect(screen.getByRole('button', { name: 'log.runtime.previous' })).toBeDisabled()
  expect(screen.queryByRole('button', { name: 'log.runtime.refresh' })).not.toBeInTheDocument()

  mock.records.mockResolvedValueOnce({ items: [{ id: 2, model_name: 'Newer record' }], next_cursor: null, snapshot_id: 'newer' })
  await user.click(search)
  expect(await screen.findByText('Newer record')).toBeVisible()
  expect(mock.records).toHaveBeenLastCalledWith('model', expectedFilters, undefined)
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
  expect(screen.getAllByText('log.runtime.notRecorded').length).toBeGreaterThan(0)
  expect(screen.queryByText('PRIVATE_BODY')).not.toBeInTheDocument()
})

it('uses readable identities instead of separate surrogate-ID columns', async () => {
  mock.records.mockResolvedValue({ items: [{ id: 36, actor_kind: 'hosted_app', actor_id: 10,
    actor_name: 'Recorded application', subject_kind: 'app_self', subject_id: null,
    credential_id: 143, credential_mask: 'bs-app-********ABCD', result: 'upstream_failed' }],
    next_cursor: null, snapshot_id: 'selection' })
  render(<RuntimeAuditPanel />, { wrapper })
  expect(await screen.findByText('Recorded application')).toBeVisible()
  expect(screen.getByText('bs-app-********ABCD')).toBeVisible()
  expect(screen.getAllByText('log.runtime.values.app_self').length).toBeGreaterThan(0)
  expect(screen.queryByRole('columnheader', { name: 'log.runtime.fields.actor_id' })).not.toBeInTheDocument()
  expect(screen.queryByRole('columnheader', { name: 'log.runtime.fields.credential_id' })).not.toBeInTheDocument()
  expect(screen.queryByText('143')).not.toBeInTheDocument()
})

it('shows the recorded visitor name without a redundant numeric user column', async () => {
  mock.records.mockResolvedValue({ items: [{ id: 58, user_id: 3, user_name: 'Recorded visitor' }],
    next_cursor: null, snapshot_id: 'selection' })
  render(<RuntimeAuditPanel />, { wrapper })
  fireEvent.click(screen.getByRole('radio', { name: 'log.runtime.accessTab' }))
  expect(await screen.findByText('Recorded visitor')).toBeVisible()
  expect(screen.queryByRole('columnheader', { name: 'log.runtime.fields.user_id' })).not.toBeInTheDocument()
  expect(screen.getByRole('columnheader', { name: 'log.runtime.fields.operator_dept_path' })).toBeVisible()
})

it('sends the organisation as a comma string only after apply', async () => {
  mock.departments.mockResolvedValue({
    active: [
      { id: 2, dept_id: 'BS@2', external_id: null, name: 'Sales', path_name: 'Root/Sales', parent_id: 1, tenant_id: 1, has_children: false },
      { id: 9, dept_id: 'BS@9', external_id: null, name: 'Ops', path_name: 'Root/Ops', parent_id: 1, tenant_id: 1, has_children: false },
    ],
    archived: [], show_none: true, show_unrecorded: false,
  })
  render(<RuntimeAuditPanel />, { wrapper })
  await waitFor(() => expect(mock.records).toHaveBeenCalled())
  expect(screen.getAllByRole('button')[0]).toHaveAccessibleName('log.org.placeholder')
  fireEvent.click(screen.getByRole('button', { name: 'log.org.placeholder' }))
  fireEvent.click(await screen.findByRole('checkbox', { name: /Sales/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: /Ops/ }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'log.org.none' }))
  fireEvent.click(screen.getByRole('button', { name: 'log.org.confirm' }))
  expect(mock.records).not.toHaveBeenLastCalledWith('model', expect.objectContaining({ dept_ids: expect.anything() }), undefined)
  fireEvent.click(screen.getByRole('button', { name: 'log.runtime.apply' }))
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', expect.objectContaining({
    dept_ids: '2,9', include_descendants: 'true', include_none: 'true',
  }), undefined))
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

it('accepts either date boundary and resets to the first page of the default time range', async () => {
  const user = userEvent.setup()
  mock.records.mockResolvedValueOnce({ items: [], next_cursor: 'recent-next', snapshot_id: 'recent', matched_count: null })
  render(<RuntimeAuditPanel />, { wrapper })
  const next = screen.getByRole('button', { name: 'log.runtime.next' })
  await waitFor(() => expect(next).toBeEnabled())
  await user.click(next)
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', { time_range: 'recent7d', tenant_id: undefined }, 'recent-next'))
  await user.click(screen.getByRole('combobox', { name: 'log.runtime.timeRange' }))
  await user.click(screen.getByRole('option', { name: 'log.runtime.custom' }))
  const start = screen.getByRole('combobox', { name: 'datePicker.startDate' })
  const end = screen.getByRole('combobox', { name: 'datePicker.endDate' })
  const search = screen.getByRole('button', { name: 'log.runtime.apply' })
  await user.click(search)
  expect(screen.getByRole('alert')).toHaveTextContent('log.runtime.invalidRange')
  fireEvent.change(start, { target: { value: '2026-10-20' } })
  fireEvent.keyDown(start, { key: 'Enter' })
  expect(end).toHaveAttribute('placeholder', 'datePicker.unlimited')
  await user.click(search)
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', expect.objectContaining({
    time_range: 'custom', start_time: new Date(2026, 9, 20).toISOString(), end_time: undefined,
  }), undefined))
  fireEvent.change(end, { target: { value: '2026-10-21' } })
  fireEvent.keyDown(end, { key: 'Enter' })
  fireEvent.change(start, { target: { value: '' } })
  fireEvent.keyDown(start, { key: 'Enter' })
  expect(start).toHaveAttribute('placeholder', 'datePicker.unlimited')
  await user.click(search)
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', expect.objectContaining({
    time_range: 'custom', start_time: undefined,
    end_time: new Date(2026, 9, 21, 23, 59, 59).toISOString().replace('.000Z', '.999999Z'),
  }), undefined))
  await user.click(screen.getByRole('button', { name: 'log.resetButton' }))
  expect(screen.getByRole('combobox', { name: 'log.runtime.timeRange' })).toHaveTextContent('log.runtime.recent7d')
  expect(screen.queryByRole('combobox', { name: 'datePicker.startDate' })).not.toBeInTheDocument()
  await waitFor(() => expect(mock.records).toHaveBeenLastCalledWith('model', { time_range: 'recent7d', tenant_id: undefined }, undefined))
  expect(screen.getByRole('button', { name: 'log.runtime.previous' })).toBeDisabled()
})
