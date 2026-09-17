import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { getDshUsageOverview } from '@/controllers/API/dsh'
import type { DshUsageOverviewPage, DshUsageOverviewUser } from '@/types/dsh'
import { UsageUserSelect } from './UsageUserSelect'

vi.mock('@/controllers/API/dsh', () => ({ getDshUsageOverview: vi.fn() }))

const range = { startAt: '2026-09-09T00:00:00+08:00', endAt: '2026-09-15T12:00:00+08:00' }
const metrics = {
    message_count: 0,
    qa_count: 0,
    failed_count: 0,
    cancelled_count: 0,
    running_count: 0,
    usage_unknown_count: 0,
    recorded_usage_count: 0,
    missing_usage_count: 0,
    input_tokens: 0,
    output_tokens: 0,
    total_tokens: 0,
}
const users: DshUsageOverviewUser[] = ['admin', 'alice', 'bob', 'charlie'].map((name, index) => ({
    user_id: index + 1,
    user_name: name,
    department_id: 10,
    department_name: 'Research',
    metrics,
}))
function page(items = users, cursor: string | null = null): DshUsageOverviewPage {
    return {
        tenant_id: 2,
        start_at: range.startAt,
        end_at: range.endAt,
        timezone: 'Asia/Shanghai',
        department_id: null,
        totals: metrics,
        items,
        next_cursor: cursor,
        has_more: !!cursor,
    }
}
function open(onChange = vi.fn()) {
    render(<UsageUserSelect value={users[0]} range={range} onChange={onChange} />)
    fireEvent.click(screen.getByLabelText('dsh.selectUsageUser'))
    return onChange
}
beforeEach(() => {
    vi.resetAllMocks()
    vi.mocked(getDshUsageOverview).mockResolvedValue(page())
})

describe('usage user dropdown', () => {
    it('opens with tenant users in a fixed-height scrollable list and selects a row', async () => {
        const onChange = open()
        const alice = await screen.findByRole('option', { name: /alice/ })
        expect(screen.getAllByRole('option')).toHaveLength(4)
        expect(screen.getByRole('listbox')).toHaveClass('h-60', 'overflow-y-auto')
        expect(getDshUsageOverview).toHaveBeenCalledWith(
            expect.objectContaining({ keyword: undefined, limit: 20 }),
            expect.any(AbortSignal),
        )
        expect(screen.queryByText('dsh.typeToSearchUser')).toBeNull()
        fireEvent.click(alice)
        expect(onChange).toHaveBeenCalledWith(users[1])
        expect(screen.queryByRole('option')).toBeNull()
    })
    it('filters remotely and restores the list when search is cleared', async () => {
        vi.mocked(getDshUsageOverview).mockImplementation(async (query) =>
            page(query.keyword ? [users[1]] : users),
        )
        open()
        await screen.findByRole('option', { name: /bob/ })
        fireEvent.change(screen.getByPlaceholderText('dsh.searchUsers'), { target: { value: 'ali' } })
        await waitFor(() => expect(screen.getAllByRole('option')).toHaveLength(1))
        expect(screen.getByRole('option')).toHaveTextContent('alice')
        fireEvent.change(screen.getByPlaceholderText('dsh.searchUsers'), { target: { value: '' } })
        await screen.findByRole('option', { name: /bob/ })
        expect(screen.getAllByRole('option')).toHaveLength(4)
    })
    it('appends and deduplicates subsequent pages while keeping earlier users selectable', async () => {
        vi.mocked(getDshUsageOverview)
            .mockResolvedValueOnce(page(users.slice(0, 2), 'next'))
            .mockResolvedValueOnce(page(users.slice(1)))
        open()
        fireEvent.click(await screen.findByRole('option', { name: 'dsh.loadMoreUsers' }))
        await screen.findByRole('option', { name: /charlie/ })
        expect(screen.getAllByRole('option')).toHaveLength(4)
        expect(screen.getByRole('option', { name: /admin/ })).toBeTruthy()
        expect(getDshUsageOverview).toHaveBeenLastCalledWith(
            expect.objectContaining({ cursor: 'next' }),
            expect.any(AbortSignal),
        )
    })
    it('loads another page when the list is scrolled to the bottom', async () => {
        vi.mocked(getDshUsageOverview)
            .mockResolvedValueOnce(page(users.slice(0, 2), 'next'))
            .mockResolvedValueOnce(page(users.slice(2)))
        open()
        await screen.findByRole('option', { name: /alice/ })
        fireEvent.scroll(screen.getByRole('listbox'))
        await screen.findByRole('option', { name: /charlie/ })
        expect(screen.getAllByRole('option')).toHaveLength(4)
    })
    it('preserves loaded users on a pagination failure and supports retry', async () => {
        vi.mocked(getDshUsageOverview)
            .mockResolvedValueOnce(page(users.slice(0, 2), 'next'))
            .mockRejectedValueOnce(new Error('unavailable'))
            .mockResolvedValueOnce(page(users.slice(2)))
        open()
        fireEvent.click(await screen.findByRole('option', { name: 'dsh.loadMoreUsers' }))
        await screen.findByRole('alert')
        expect(screen.getByRole('option', { name: /alice/ })).toBeTruthy()
        fireEvent.click(screen.getByRole('option', { name: 'dsh.refresh' }))
        await screen.findByRole('option', { name: /charlie/ })
        expect(screen.getAllByRole('option')).toHaveLength(4)
    })
    it('ignores a slow earlier search result after a newer keyword resolves', async () => {
        let resolveOld: (value: DshUsageOverviewPage) => void = () => {}
        vi.mocked(getDshUsageOverview).mockImplementation(async (query) => {
            if (query.keyword === 'old')
                return new Promise((resolve) => {
                    resolveOld = resolve
                })
            return page(query.keyword === 'new' ? [users[2]] : users)
        })
        open()
        await screen.findByRole('option', { name: /alice/ })
        fireEvent.change(screen.getByPlaceholderText('dsh.searchUsers'), { target: { value: 'old' } })
        await waitFor(() =>
            expect(getDshUsageOverview).toHaveBeenCalledWith(
                expect.objectContaining({ keyword: 'old' }),
                expect.any(AbortSignal),
            ),
        )
        fireEvent.change(screen.getByPlaceholderText('dsh.searchUsers'), { target: { value: 'new' } })
        await screen.findByRole('option', { name: /bob/ })
        await act(async () => resolveOld(page([users[1]])))
        expect(screen.queryByRole('option', { name: /alice/ })).toBeNull()
        expect(screen.getByRole('option', { name: /bob/ })).toBeTruthy()
    })
    it('shows a real empty state and keeps keyboard selection available', async () => {
        vi.mocked(getDshUsageOverview).mockResolvedValueOnce(page([]))
        const onChange = open()
        expect(await screen.findByRole('status')).toBeTruthy()
        await screen.findByText('dsh.empty')
        fireEvent.change(screen.getByPlaceholderText('dsh.searchUsers'), { target: { value: 'a' } })
        await screen.findByRole('option', { name: /alice/ })
        fireEvent.keyDown(screen.getByPlaceholderText('dsh.searchUsers'), { key: 'ArrowDown' })
        fireEvent.keyDown(screen.getByPlaceholderText('dsh.searchUsers'), { key: 'Enter' })
        expect(onChange).toHaveBeenCalled()
    })
})
