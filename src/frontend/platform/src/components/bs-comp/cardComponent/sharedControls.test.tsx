import { AppType } from '@/types/app'
import { cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react'
import { afterEach,expect,it,vi } from 'vitest'
import CardComponent from './index'

afterEach(cleanup)
it('keeps application publish state unchanged when the server rejects the transition', async () => {
    const onCheckedChange = vi.fn().mockResolvedValue(false)
    const onOpen = vi.fn()
    render(<CardComponent id="app" data={{ id: 'app' }} type={AppType.ASSISTANT} title="Assistant" description="" checked={false}
        edit onClick={onOpen} onCheckedChange={onCheckedChange} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(onCheckedChange).toHaveBeenCalledWith(true, { id: 'app' }))
    expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'false')
    expect(onOpen).not.toHaveBeenCalled()
})
it('updates accepted publish state and retains both status labels', async () => {
    const onCheckedChange = vi.fn().mockResolvedValue(true)
    render(<CardComponent id="app" data={{ id: 'app' }} type={AppType.ASSISTANT} title="Assistant" description="" checked={false}
        edit onClick={() => undefined} onCheckedChange={onCheckedChange} />)
    fireEvent.click(screen.getByRole('switch'))
    await waitFor(() => expect(screen.getByRole('switch')).toHaveAttribute('aria-checked', 'true'))
    expect(screen.getByText('skills.online')).toBeInTheDocument()
    expect(screen.getByText('skills.offline')).toBeInTheDocument()
})
