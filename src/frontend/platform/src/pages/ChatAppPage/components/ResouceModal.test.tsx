import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { ResouceContent } from './ResouceModal'

vi.mock('../../../controllers/API', () => ({
    getSourceChunksApi: vi.fn().mockResolvedValue([]),
    splitWordApi: vi.fn().mockResolvedValue([]),
}))
vi.mock('./FileViewPanne', () => ({ default: () => null }))

it('renders the source panel buttons when a reference is opened', async () => {
    render(<ResouceContent data={{ chatId: 'chat-1', messageId: 'msg-1', message: 'answer' }} setOpen={() => {}} />)
    expect(await screen.findByRole('button', { name: 'chat.addCustomLabel' })).toBeVisible()
})
