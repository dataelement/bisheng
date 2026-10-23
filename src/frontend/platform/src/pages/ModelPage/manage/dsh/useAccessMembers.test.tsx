import { act, fireEvent, render, screen } from '@testing-library/react'
import { StrictMode, useState } from 'react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { getDshModelUserPermissions } from '@/controllers/API/dsh'
import type { DshModelUserPermissionPage } from '@/types/dsh'
import { AccessMembersProvider, useAccessMembers, useDelayedMemberLoading } from './useAccessMembers'

vi.mock('@/controllers/API/dsh', () => ({ getDshModelUserPermissions: vi.fn() }))
const remember = vi.fn()
const empty: DshModelUserPermissionPage = {
    tenant_id: 1,
    model: { id: 7, name: 'Model', is_root_shared: false },
    items: [],
    has_more: false,
    next_cursor: null,
}
function Members({ modelId }: { modelId: number }) {
    const state = useAccessMembers(modelId, 31, undefined, remember)
    const indicator = useDelayedMemberLoading(state.loading)
    return (
        <>
            <span data-testid="page">{state.page ? state.page.items.length : 'pending'}</span>
            {indicator && <span role="status">Loading</span>}
            {state.error && <button onClick={state.retry}>Retry</button>}
            {state.page?.has_more && <button onClick={state.more}>More</button>}
        </>
    )
}
function Harness({ refresh = 0, modelId = 7 }: { refresh?: number; modelId?: number }) {
    const [open, setOpen] = useState(true)
    return (
        <AccessMembersProvider modelId={modelId} refresh={refresh}>
            <button onClick={() => setOpen((value) => !value)}>Toggle</button>
            {open && <Members modelId={modelId} />}
        </AccessMembersProvider>
    )
}
const advance = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms))
beforeEach(() => {
    vi.useFakeTimers()
    vi.resetAllMocks()
    vi.mocked(getDshModelUserPermissions).mockResolvedValue(empty)
})
afterEach(() => {
    vi.useRealTimers()
})

it('reuses an empty result when a department is collapsed and reopened', async () => {
    render(<Harness />)
    await advance()
    expect(screen.getByTestId('page')).toHaveTextContent('0')
    fireEvent.click(screen.getByText('Toggle'))
    fireEvent.click(screen.getByText('Toggle'))
    expect(screen.getByTestId('page')).toHaveTextContent('0')
    await advance()
    expect(getDshModelUserPermissions).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('status')).toBeNull()
})

it('shares an in-flight request across collapse and reopen and cancels it on dialog close', async () => {
    vi.mocked(getDshModelUserPermissions).mockReturnValue(new Promise(() => {}))
    const view = render(<Harness />)
    await advance()
    const signal = vi.mocked(getDshModelUserPermissions).mock.calls[0][2]!
    fireEvent.click(screen.getByText('Toggle'))
    expect(signal.aborted).toBe(false)
    fireEvent.click(screen.getByText('Toggle'))
    await advance()
    expect(getDshModelUserPermissions).toHaveBeenCalledTimes(1)
    view.unmount()
    expect(signal.aborted).toBe(true)
})

it('invalidates pages after a save and when model context changes', async () => {
    const view = render(<Harness />)
    await advance()
    view.rerender(<Harness refresh={1} />)
    await advance()
    expect(getDshModelUserPermissions).toHaveBeenCalledTimes(2)
    view.rerender(<Harness refresh={1} modelId={8} />)
    await advance()
    expect(getDshModelUserPermissions).toHaveBeenCalledTimes(3)
    expect(getDshModelUserPermissions).toHaveBeenLastCalledWith(8, expect.anything(), expect.any(AbortSignal))
})

it('discards an old response when the save generation changes', async () => {
    let complete!: (page: DshModelUserPermissionPage) => void
    vi.mocked(getDshModelUserPermissions).mockReturnValueOnce(
        new Promise((resolve) => {
            complete = resolve
        }),
    )
    const view = render(<Harness />)
    await advance()
    view.rerender(<Harness refresh={1} />)
    await advance()
    await act(async () => {
        complete({ ...empty, has_more: true, next_cursor: '99' })
    })
    expect(screen.queryByText('More')).toBeNull()
    expect(screen.getByTestId('page')).toHaveTextContent('0')
})

it('shows a delayed inline indicator for slow reads and keeps it visible for 300ms', async () => {
    let complete!: (page: DshModelUserPermissionPage) => void
    vi.mocked(getDshModelUserPermissions).mockReturnValueOnce(
        new Promise((resolve) => {
            complete = resolve
        }),
    )
    render(<Harness />)
    await advance(299)
    expect(screen.queryByRole('status')).toBeNull()
    await advance(1)
    expect(screen.getByRole('status')).toBeTruthy()
    await act(async () => {
        complete(empty)
    })
    await advance(299)
    expect(screen.getByRole('status')).toBeTruthy()
    await advance(1)
    expect(screen.queryByRole('status')).toBeNull()
})

it('retries a failed read without caching the error', async () => {
    vi.mocked(getDshModelUserPermissions).mockRejectedValueOnce(new Error('temporarily unavailable'))
    render(<Harness />)
    await advance()
    fireEvent.click(screen.getByText('Retry'))
    await advance()
    expect(getDshModelUserPermissions).toHaveBeenCalledTimes(2)
    expect(screen.getByTestId('page')).toHaveTextContent('0')
})

it('preserves the pagination cursor and deduplicates repeated load-more clicks', async () => {
    vi.mocked(getDshModelUserPermissions).mockResolvedValueOnce({
        ...empty,
        has_more: true,
        next_cursor: '50',
    })
    render(<Harness />)
    await advance()
    fireEvent.click(screen.getByText('More'))
    fireEvent.click(screen.getByText('More'))
    await advance()
    expect(getDshModelUserPermissions).toHaveBeenCalledTimes(2)
    expect(getDshModelUserPermissions).toHaveBeenLastCalledWith(
        7,
        expect.objectContaining({ cursor: '50', limit: 50 }),
        expect.any(AbortSignal),
    )
    expect(screen.queryByText('More')).toBeNull()
})

it('loads successfully during StrictMode effect replay', async () => {
    render(
        <StrictMode>
            <Harness />
        </StrictMode>,
    )
    await advance()
    expect(getDshModelUserPermissions).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('page')).toHaveTextContent('0')
})
