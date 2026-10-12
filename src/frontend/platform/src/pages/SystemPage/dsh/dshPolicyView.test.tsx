import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getDshUsageOverview, getDshUsageTimeSummary } from '@/controllers/API/dsh'
import type { DshUsageTimeSummary } from '@/types/dsh'
import { PolicyView } from './PolicyView'

vi.mock('react-i18next', () => ({
    useTranslation: () => ({ t: (key: string) => key, i18n: { language: 'zh-Hans' } }),
}))
vi.mock('@/controllers/API/dsh', () => ({ getDshUsageOverview: vi.fn(), getDshUsageTimeSummary: vi.fn() }))
vi.mock('@/contexts/userContext', async () => ({
    userContext: (await import('react')).createContext({ user: { user_id: 20, user_name: 'alice' } }),
}))
vi.mock('@/components/bs-comp/department/TreeDepartmentSelect', () => ({
    TreeDepartmentSelect: ({
        onChange,
        noneLabel,
    }: {
        onChange: (id: number | null, node: { name: string } | null) => void
        noneLabel: string
    }) => (
        <>
            <button onClick={() => onChange(10, { name: 'Research' })}>pick-department</button>
            <button onClick={() => onChange(null, null)}>{noneLabel}</button>
        </>
    ),
}))

const metrics = {
    message_count: 2,
    qa_count: 1,
    failed_count: 1,
    cancelled_count: 0,
    running_count: 0,
    usage_unknown_count: 0,
    recorded_usage_count: 2,
    missing_usage_count: 0,
    input_tokens: 10,
    output_tokens: 5,
    total_tokens: 15,
}
function summary(range: { startAt: string; endAt: string }): DshUsageTimeSummary {
    const granularity = Date.parse(range.endAt) - Date.parse(range.startAt) <= 48 * 3600000 ? 'hour' : 'day'
    return {
        start_at: range.startAt,
        end_at: range.endAt,
        timezone: 'Asia/Shanghai',
        granularity,
        totals: metrics,
        points: [{ ...metrics, start_at: range.startAt, end_at: range.endAt }],
    }
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.spyOn(Date, 'now').mockReturnValue(Date.parse('2026-09-15T16:00:00+08:00'))
    vi.stubGlobal(
        'ResizeObserver',
        class {
            observe() {}
            unobserve() {}
            disconnect() {}
        },
    )
    Element.prototype.scrollIntoView = vi.fn()
    vi.mocked(getDshUsageOverview).mockImplementation(async (query) => ({
        tenant_id: 2,
        start_at: query.startAt,
        end_at: query.endAt,
        timezone: 'Asia/Shanghai',
        department_id: query.departmentId ?? null,
        totals: metrics,
        summary: query.includeSummary ? summary(query) : null,
        items: [{ user_id: 20, user_name: 'alice', department_id: 10, department_name: 'Research', metrics }],
        next_cursor: null,
        has_more: false,
    }))
    vi.mocked(getDshUsageTimeSummary).mockImplementation(async (_id, range) => summary(range))
})

describe('unified usage selection', () => {
    it('loads the entire tenant on switching to departments and restores it after clearing selection', async () => {
        render(<PolicyView />)
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.byDepartment' }), {
            button: 0,
            ctrlKey: false,
        })
        await screen.findByRole('heading', { name: 'dsh.entireTenant' })
        await screen.findByText('15')
        expect(getDshUsageOverview).toHaveBeenCalledWith(
            expect.objectContaining({ departmentId: undefined, includeSummary: true }),
            expect.any(AbortSignal),
        )
        expect(screen.queryByText('dsh.selectDepartmentForUsage')).toBeNull()
        fireEvent.click(screen.getByText('pick-department'))
        await screen.findByRole('heading', { name: 'Research' })
        fireEvent.click(screen.getByRole('button', { name: 'dsh.entireTenant' }))
        await screen.findByRole('heading', { name: 'dsh.entireTenant' })
        expect(screen.queryByText('dsh.usageMemberDetails')).toBeNull()
        expect(screen.queryByRole('table')).toBeNull()
    })
    it('prefers admin when visible on the first user page', async () => {
        const original = vi.mocked(getDshUsageOverview).getMockImplementation()!
        vi.mocked(getDshUsageOverview).mockImplementation(async (query, signal) => {
            const page = await original(query, signal)
            return { ...page, items: [...page.items, { ...page.items[0], user_id: 1, user_name: 'admin' }] }
        })
        render(<PolicyView />)
        await screen.findByRole('heading', { name: 'Research / admin' })
    })
    it('finds the current user beyond the first page before choosing a fallback', async () => {
        vi.mocked(getDshUsageOverview).mockResolvedValueOnce({
            tenant_id: 2,
            start_at: '',
            end_at: '',
            timezone: 'Asia/Shanghai',
            department_id: null,
            totals: metrics,
            items: [
                { user_id: 30, user_name: 'bob', department_id: 10, department_name: 'Research', metrics },
            ],
            next_cursor: 'next',
            has_more: true,
        })
        render(<PolicyView />)
        await screen.findByRole('heading', { name: 'Research / alice' })
        expect(getDshUsageOverview).toHaveBeenCalledWith(
            expect.objectContaining({ keyword: 'alice', limit: 100 }),
            expect.any(AbortSignal),
        )
        expect(getDshUsageTimeSummary).toHaveBeenCalledWith('20', expect.any(Object), expect.any(AbortSignal))
        expect(getDshUsageTimeSummary).not.toHaveBeenCalledWith(
            '30',
            expect.any(Object),
            expect.any(AbortSignal),
        )
    })
    it('keeps user candidates in the search dropdown and retains selection when changing dates', async () => {
        render(<PolicyView />)
        await screen.findByRole('heading', { name: 'Research / alice' })
        fireEvent.click(screen.getByLabelText('dsh.selectUsageUser'))
        await screen.findByRole('option', { name: /alice/u })
        expect(screen.queryByRole('table')).toBeNull()
        fireEvent.change(screen.getByPlaceholderText('dsh.searchUsers'), { target: { value: 'ali' } })
        fireEvent.click(await screen.findByRole('option', { name: /alice/u }))
        await screen.findByRole('heading', { name: 'Research / alice' })
        await screen.findByText('15')
        expect(screen.queryByRole('option')).toBeNull()
        expect(screen.queryByRole('table')).toBeNull()
        fireEvent.click(screen.getByLabelText('dsh.usageRange'))
        fireEvent.click(screen.getByText('dsh.range.today'))
        await waitFor(() => expect(getDshUsageTimeSummary).toHaveBeenCalledTimes(2))
        expect(screen.getByRole('heading', { name: 'Research / alice' })).toBeTruthy()
        await waitFor(() => expect(document.querySelector('[data-usage-line-chart="tokens"]')).toBeTruthy())
        expect(getDshUsageOverview).toHaveBeenCalledWith(
            expect.objectContaining({ keyword: 'ali' }),
            expect.any(AbortSignal),
        )
    })
    it('shows department aggregate usage without a member-detail section', async () => {
        render(<PolicyView />)
        fireEvent.mouseDown(screen.getByRole('tab', { name: 'dsh.byDepartment' }), {
            button: 0,
            ctrlKey: false,
        })
        fireEvent.click(screen.getByText('pick-department'))
        await screen.findByText('15')
        expect(screen.queryByRole('table')).toBeNull()
        expect(getDshUsageOverview).toHaveBeenCalledWith(
            expect.objectContaining({ departmentId: 10, includeSummary: true }),
            expect.any(AbortSignal),
        )
        expect(screen.queryByText('dsh.usageMemberDetails')).toBeNull()
        expect(screen.queryByRole('table')).toBeNull()
        const departmentRequests = vi
            .mocked(getDshUsageOverview)
            .mock.calls.map(([query]) => query)
            .filter((query) => query.departmentId === 10)
        expect(departmentRequests.length).toBeGreaterThan(0)
        expect(departmentRequests.every((query) => query.includeSummary === true)).toBe(true)
    })
    it('offers the three fixed time ranges without custom date controls', async () => {
        render(<PolicyView />)
        await screen.findByRole('heading', { name: 'Research / alice' })
        fireEvent.click(screen.getByLabelText('dsh.usageRange'))
        expect(screen.getByText('dsh.range.today')).toBeTruthy()
        expect(screen.queryByText('dsh.range.7d')).toBeNull()
        expect(screen.getByText('dsh.range.30d')).toBeTruthy()
        expect(screen.getAllByText('dsh.range.year')).toHaveLength(2)
        expect(screen.queryByText('dsh.range.custom')).toBeNull()
        expect(screen.queryByLabelText('dsh.rangeStart')).toBeNull()
    })
    it('places filters in the supplied header target and removes them on unmount', async () => {
        const target = document.createElement('div')
        document.body.append(target)
        const view = render(<PolicyView toolbarTarget={target} />)
        await screen.findByRole('heading', { name: 'Research / alice' })
        expect(target).toContainElement(screen.getByLabelText('dsh.usageFilters'))
        expect(view.container.querySelector('[aria-label="dsh.usageFilters"]')).toBeNull()
        view.unmount()
        expect(target).toBeEmptyDOMElement()
        target.remove()
    })
    it('selects the first available tenant user when the current user is absent', async () => {
        vi.mocked(getDshUsageOverview).mockResolvedValueOnce({
            tenant_id: 2,
            start_at: '',
            end_at: '',
            timezone: 'Asia/Shanghai',
            department_id: null,
            totals: metrics,
            items: [
                { user_id: 30, user_name: 'bob', department_id: 10, department_name: 'Research', metrics },
            ],
            next_cursor: null,
            has_more: false,
        })
        render(<PolicyView />)
        await screen.findByRole('heading', { name: 'Research / bob' })
        expect(getDshUsageTimeSummary).toHaveBeenCalledWith('30', expect.any(Object), expect.any(AbortSignal))
    })
})
