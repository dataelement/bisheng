import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import DailyChatDetail from './dailyChatDetail'

const mock = vi.hoisted(() => ({ history: vi.fn(), source: vi.fn() }))
vi.mock('@/controllers/API', () => ({ getChatHistoryApi: mock.history }))
vi.mock('@/pages/ChatAppPage/components/ResouceModal', async () => {
    const React = await import('react')
    return { default: React.forwardRef((_, ref) => { React.useImperativeHandle(ref, () => ({ openModal: mock.source })); return null }) }
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('keeps daily JSON history, reasoning toggle, errors and source-modal payloads', async () => {
    mock.history.mockResolvedValue([
        { messageId: 'q1', isCreatedByUser: true, user_name: 'Alice', text: '{"query":"Original question"}' },
        { messageId: 'a1', isCreatedByUser: false, sender: 'Assistant', source: 1, text: '{"msg":"Final answer","events":[{"type":"thinking","content":"Reasoning details"}]}' },
        { messageId: 'a2', isCreatedByUser: false, sender: 'Assistant', text: '{"content":"Older answer","reasoning_content":"Older reasoning"}' },
        { messageId: 'e1', isCreatedByUser: false, sender: 'Assistant', text: 'Model failed', error: true },
    ])
    render(<MemoryRouter initialEntries={['/log/chatlog/chat-1']}><Routes><Route path="/log/chatlog/:cid" element={<DailyChatDetail />} /></Routes></MemoryRouter>)
    await screen.findByText('Original question')
    expect(screen.getByText('Final answer')).toBeVisible()
    expect(screen.getByText('Older answer')).toBeVisible()
    expect(screen.getByText('Model failed')).toBeVisible()
    expect(screen.queryByText('Reasoning details')).not.toBeInTheDocument()
    const thinking = screen.getAllByRole('button', { name: 'log.thinkingContent' })[0]
    fireEvent.click(thinking)
    expect(thinking).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByText('Reasoning details')).toBeVisible()
    fireEvent.click(thinking)
    expect(screen.queryByText('Reasoning details')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'chat.source' }))
    await waitFor(() => expect(mock.source).toHaveBeenCalledWith({ chatId: 'chat-1', messageId: 'a1', message: ':::thinking\nReasoning details\n:::\nFinal answer' }))
})
