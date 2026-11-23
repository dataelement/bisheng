import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import DailyChatDetail from './dailyChatDetail'

const mock = vi.hoisted(() => ({ history: vi.fn(), source: vi.fn(), resolve: vi.fn() }))
vi.mock('@/controllers/API', () => ({
    getChatHistoryApi: mock.history,
    resolveCitationDetails: mock.resolve,
    getCitationDetail: vi.fn().mockResolvedValue(null),
    getCitationUnresolvedReason: vi.fn(),
}))
vi.mock('@/pages/ChatAppPage/components/ResouceModal', async () => {
    const React = await import('react')
    return { default: React.forwardRef((_, ref) => { React.useImperativeHandle(ref, () => ({ openModal: mock.source })); return null }) }
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('keeps daily JSON history, reasoning toggle, errors and source-modal payloads', async () => {
    const avatar = '/object/public/avatar/14/history.png?signature=example'
    mock.history.mockResolvedValue([
        { messageId: 'q1', isCreatedByUser: true, user_name: 'Alice', user_avatar: avatar, text: '{"query":"Original question"}' },
        { messageId: 'a1', isCreatedByUser: false, sender: 'Assistant', source: 1, text: '{"msg":"Final answer","events":[{"type":"thinking","content":"Reasoning details"}]}' },
        { messageId: 'a2', isCreatedByUser: false, sender: 'Assistant', text: '{"content":"Older answer","reasoning_content":"Older reasoning"}' },
        { messageId: 'e1', isCreatedByUser: false, sender: 'Assistant', text: 'Model failed', error: true },
    ])
    render(<MemoryRouter initialEntries={['/log/chatlog/chat-1']}><Routes><Route path="/log/chatlog/:cid" element={<DailyChatDetail />} /></Routes></MemoryRouter>)
    await screen.findByText('Original question')
    const senderImage = screen.getByAltText('')
    expect(senderImage).toHaveAttribute('src', avatar)
    fireEvent.error(senderImage)
    expect(screen.getByText('A')).toBeInTheDocument()
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

it('renders a citation badge and reference entry from the answer marker', async () => {
    mock.resolve.mockResolvedValue([{ citationId: 'websearch_232d45ee', type: 'web', sourcePayload: { title: 'Weather', url: 'https://weather.example' } }])
    mock.history.mockResolvedValue([
        { messageId: 'q1', isCreatedByUser: true, user_name: 'AD', text: 'Weather document' },
        { messageId: 'a1', isCreatedByUser: false, sender: 'gpt-5.6-terra', text: 'The document covers the city weather.\ue200websearch_232d45ee:1\ue202' },
    ])
    render(<MemoryRouter initialEntries={['/log/chatlog/chat-1']}><Routes><Route path="/log/chatlog/:cid" element={<DailyChatDetail />} /></Routes></MemoryRouter>)
    const badge = await screen.findByRole('button', { name: 'shared:app_chat.citation.badge_aria' })
    expect(badge).toHaveAttribute('data-citation-id', 'websearch_232d45ee')
    expect(badge).toHaveTextContent('1')
    expect(screen.getByRole('button', { name: 'shared:citations.com_message.source_panel_label' })).toBeVisible()
    await waitFor(() => expect(mock.resolve).toHaveBeenCalledWith(['websearch_232d45ee']))
    expect(screen.getAllByRole('button', { name: 'shared:citations.com_message.source_panel_label' })).toHaveLength(1)
})
