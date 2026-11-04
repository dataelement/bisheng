import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { EMPTY_ORG_SELECTION } from '@/controllers/API/log'
import type { AuditDeptNode, OrgSelection } from '@/types/api/audit'
import { OrgFilter } from './index'
import { orgLabel } from './orgLabel'

const mock = vi.hoisted(() => ({ departments: vi.fn() }))
vi.mock('@/controllers/API/log', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/controllers/API/log')>()),
  getAuditDepartmentsApi: mock.departments,
}))

const node = (id: number, name: string, extra: Partial<AuditDeptNode> = {}): AuditDeptNode => ({
  id, dept_id: `BS@${id}`, external_id: null, name, path_name: `Root/${name}`, parent_id: 1, tenant_id: 1, has_children: false, ...extra,
})

const roots = (overrides = {}) => ({
  active: [node(2, 'Sales', { has_children: true })],
  archived: [node(4, 'OldTeam')],
  show_none: true,
  show_unrecorded: true,
  ...overrides,
})

const renderFilter = (value: OrgSelection = { ...EMPTY_ORG_SELECTION }) => {
  const onChange = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } })
  render(<QueryClientProvider client={client}><OrgFilter value={value} onChange={onChange} /></QueryClientProvider>)
  return onChange
}

const openPanel = async () => {
  fireEvent.click(screen.getByRole('button', { name: 'log.org.placeholder' }))
  await screen.findByText('Sales')
}

afterEach(cleanup)
beforeEach(() => {
  vi.clearAllMocks()
  mock.departments.mockImplementation(({ parentId }: { parentId?: number }) => Promise.resolve(
    parentId === 2 ? roots({ active: [node(3, 'East')], archived: [] }) : roots(),
  ))
})

it('hands the draft back on confirm with sub-departments included by default', async () => {
  const onChange = renderFilter()
  await openPanel()
  fireEvent.click(screen.getByRole('checkbox', { name: /Sales/ }))
  expect(onChange).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('button', { name: 'log.org.confirm' }))
  expect(onChange).toHaveBeenCalledWith({ ...EMPTY_ORG_SELECTION, deptIds: [2], includeDescendants: true })
})

it('lists archived departments separately and offers the two fixed options when allowed', async () => {
  const onChange = renderFilter()
  await openPanel()
  expect(screen.getByRole('region', { name: 'log.org.archivedSection' })).toHaveTextContent('Root/OldTeam')
  expect(screen.getByText('log.org.archived')).toBeVisible()
  fireEvent.click(screen.getByRole('checkbox', { name: 'log.org.none' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'log.org.unrecorded' }))
  fireEvent.click(screen.getByRole('checkbox', { name: 'log.org.includeDescendants' }))
  fireEvent.click(screen.getByRole('button', { name: 'log.org.confirm' }))
  expect(onChange).toHaveBeenCalledWith({ deptIds: [], includeDescendants: false, includeNone: true, includeUnrecorded: true })
})

it('hides the fixed options for a department-scoped reader', async () => {
  mock.departments.mockResolvedValue(roots({ show_none: false, show_unrecorded: false }))
  renderFilter()
  await openPanel()
  expect(screen.queryByRole('checkbox', { name: 'log.org.none' })).toBeNull()
  expect(screen.queryByRole('checkbox', { name: 'log.org.unrecorded' })).toBeNull()
})

it('loads children only when a department is expanded', async () => {
  renderFilter()
  await openPanel()
  expect(mock.departments).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: 'log.org.expand' }))
  expect(await screen.findByText('East')).toBeVisible()
  expect(mock.departments).toHaveBeenLastCalledWith(expect.objectContaining({ parentId: 2 }))
})

it('clears the selection', async () => {
  const onChange = renderFilter({ ...EMPTY_ORG_SELECTION, deptIds: [2], includeNone: true })
  expect(screen.getByRole('button', { name: 'log.org.placeholder' })).toHaveTextContent('log.org.selected')
  fireEvent.click(screen.getByRole('button', { name: 'log.org.placeholder' }))
  await screen.findByText('Sales')
  fireEvent.click(screen.getByRole('button', { name: 'log.org.clear' }))
  expect(onChange).toHaveBeenCalledWith(EMPTY_ORG_SELECTION)
})

it('searches by keyword as a flat list', async () => {
  renderFilter()
  await openPanel()
  fireEvent.change(screen.getByRole('searchbox', { name: 'log.org.search' }), { target: { value: 'E-110' } })
  await waitFor(() => expect(mock.departments).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: 'E-110' })))
})

it('captions the three sentinels', () => {
  const t = (key: string) => key
  expect(orgLabel(null, null, t)).toBe('log.org.unrecorded')
  expect(orgLabel(0, null, t)).toBe('log.org.none')
  expect(orgLabel(-1, null, t)).toBe('log.org.notApplicable')
  expect(orgLabel(3, 'Root/Sales', t)).toBe('Root/Sales')
})
