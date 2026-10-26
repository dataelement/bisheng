import { act, fireEvent, screen, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { bsConfirm } from './useConfirm'

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
