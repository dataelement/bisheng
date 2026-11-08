import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { bsConfirm } from './useConfirm'
import userEvent from '@testing-library/user-event'

vi.mock('@/controllers/request', () => ({ showApiError: vi.fn() }))

it('keeps failed async confirmations open and permits retry after releasing the lock', async () => {
    let reject: (reason: unknown) => void = () => undefined
    const onOk = vi.fn((next: () => void) => {
        if (onOk.mock.calls.length === 1) return new Promise<void>((_resolve, fail) => { reject = fail })
        next()
        return Promise.resolve()
    })
    await act(async () => { bsConfirm({ desc: 'Delete fixture?', okTxt: 'Delete fixture', onOk }) })
    fireEvent.click(await screen.findByRole('button', { name: 'Delete fixture' }))
    expect(screen.getByRole('alertdialog')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Delete fixture' })).toBeDisabled()
    await waitFor(() => expect(onOk).toHaveBeenCalledTimes(1))
    await act(async () => { reject(new Error('Delete failed')) })
    await waitFor(() => expect(screen.getByRole('button', { name: 'Delete fixture' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: 'Delete fixture' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(onOk).toHaveBeenCalledTimes(2)
})

it('releases an owner lock on Escape and lets the confirmation reopen', async () => {
    let locked = false
    const onOk = vi.fn()
    const onClose = vi.fn(() => { locked = false })
    const open = () => {
        if (locked) return
        locked = true
        bsConfirm({ desc: 'Delete workbench?', okTxt: 'Delete workbench', onOk, onClose })
    }
    await act(async () => { open() })
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    await userEvent.setup().keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(onClose).toHaveBeenCalledOnce()
    expect(onOk).not.toHaveBeenCalled()
    await act(async () => { open() })
    expect(await screen.findByRole('button', { name: 'Delete workbench' })).toBeInTheDocument()
    await userEvent.setup().keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(2)
})

it('calls onClose exactly once when successful completion aborts its owner signal', async () => {
    const scope = new AbortController()
    const onClose = vi.fn(() => scope.abort())
    const onCancel = vi.fn()
    await act(async () => { bsConfirm({ desc: 'Delete completed workbench?', okTxt: 'Complete delete', signal: scope.signal,
        onClose, onCancel, onOk: next => next() }) })
    fireEvent.click(await screen.findByRole('button', { name: 'Complete delete' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(scope.signal.aborted).toBe(true)
    expect(onClose).toHaveBeenCalledOnce()
    expect(onCancel).not.toHaveBeenCalled()
})

it('calls onClose once when cancellation also triggers Radix dismissal and owner abort', async () => {
    const scope = new AbortController()
    const onClose = vi.fn(() => scope.abort())
    const onCancel = vi.fn()
    const onOk = vi.fn()
    await act(async () => { bsConfirm({ desc: 'Cancel delete?', canelTxt: 'Cancel delete', signal: scope.signal, onClose, onCancel, onOk }) })
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel delete' }))
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(onClose).toHaveBeenCalledOnce()
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onOk).not.toHaveBeenCalled()
})

it('does not run an old deferred submit against a replacement confirmation', async () => {
    const oldOk = vi.fn()
    const newOk = vi.fn()
    await act(async () => { bsConfirm({ desc: 'Old dialog', okTxt: 'Old submit', onOk: oldOk }) })
    act(() => {
        fireEvent.click(screen.getByRole('button', { name: 'Old submit' }))
        bsConfirm({ desc: 'New dialog', okTxt: 'New submit', onOk: newOk })
    })
    await act(async () => { await Promise.resolve() })
    expect(oldOk).not.toHaveBeenCalled()
    expect(newOk).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'New submit' })).toBeEnabled()
    await userEvent.setup().keyboard('{Escape}')
})

it('does not close or unlock a replacement while an old pending submit completes', async () => {
    let finishOld: () => void = () => undefined
    let finishNew: () => void = () => undefined
    let closeNew: () => void = () => undefined
    const oldClose = vi.fn()
    const newClose = vi.fn()
    const oldOk = vi.fn((next: () => void) => new Promise<void>(resolve => { finishOld = () => { next(); resolve() } }))
    const newOk = vi.fn((next: () => void) => new Promise<void>(resolve => { finishNew = resolve; closeNew = next }))
    await act(async () => { bsConfirm({ desc: 'Old pending', okTxt: 'Old pending submit', onOk: oldOk, onClose: oldClose }) })
    fireEvent.click(screen.getByRole('button', { name: 'Old pending submit' }))
    await waitFor(() => expect(oldOk).toHaveBeenCalledOnce())
    await act(async () => { bsConfirm({ desc: 'New pending', okTxt: 'New pending submit', onOk: newOk, onClose: newClose }) })
    fireEvent.click(screen.getByRole('button', { name: 'New pending submit' }))
    await waitFor(() => expect(newOk).toHaveBeenCalledOnce())
    await act(async () => { finishOld() })
    expect(screen.getByRole('button', { name: 'New pending submit' })).toBeDisabled()
    expect(newClose).not.toHaveBeenCalled()
    expect(oldClose).not.toHaveBeenCalled()
    await act(async () => { closeNew(); finishNew() })
    expect(newClose).toHaveBeenCalledOnce()
})

it('treats Escape as acknowledgement for a hideCancel confirmation', async () => {
    const onCancel = vi.fn()
    const onClose = vi.fn()
    const onOk = vi.fn((next: () => void) => next())
    await act(async () => { bsConfirm({ desc: 'Acknowledge notice', hideCancel: true, onOk, onCancel, onClose }) })
    expect(await screen.findByRole('alertdialog')).toBeInTheDocument()
    await userEvent.setup().keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(onOk).toHaveBeenCalledOnce()
    expect(onClose).toHaveBeenCalledOnce()
    expect(onCancel).not.toHaveBeenCalled()
})

it('closes an invalidated form confirmation without submitting it', async () => {
    const scope = new AbortController()
    const onOk = vi.fn()
    await act(async () => { bsConfirm({ desc: 'Old tenant form', okTxt: 'Save old tenant', signal: scope.signal, onOk }) })
    expect(await screen.findByRole('button', { name: 'Save old tenant' })).toBeInTheDocument()
    act(() => scope.abort())
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(onOk).not.toHaveBeenCalled()
})
