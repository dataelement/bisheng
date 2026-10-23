import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import TaskAppChats from './taskAppChats'

const mock = vi.hoisted(() => ({ permission: vi.fn(), status: vi.fn(), next: vi.fn(), update: vi.fn(), assistant: vi.fn(), workflow: vi.fn(), similar: vi.fn(), qa: vi.fn(), clear: vi.fn(), change: vi.fn(), destroy: vi.fn() }))
vi.mock('@/controllers/API/log', () => ({ getMarkPermissionApi: mock.permission, getMarkStatusApi: mock.status, getNextMarkChatApi: mock.next, updateMarkStatusApi: mock.update }))
vi.mock('@/components/bs-comp/chatComponent/messageStore', () => ({ useMessageStore: () => ({ loadHistoryMsg: mock.assistant, loadMoreHistoryMsg: vi.fn(), changeChatId: mock.change, clearMsgs: mock.clear }) }))
vi.mock('@/pages/BuildPage/flow/FlowChat/messageStore', () => ({ useMessageStore: () => ({ loadHistoryMsg: mock.workflow, loadMoreHistoryMsg: vi.fn(), changeChatId: mock.change, clearMsgs: mock.clear }) }))
vi.mock('@/store/assistantStore', () => ({ useAssistantStore: () => ({ destroy: mock.destroy }) }))
vi.mock('@/components/bs-comp/chatComponent/MessagePanne', () => ({ default: ({ onMarkClick }: { onMarkClick: (type: string, id: string, qa: { q: string; a: string }) => void }) => <button onClick={() => onMarkClick('question', 'message-1', { q: 'Question', a: 'Answer' })}>Assistant annotation</button> }))
vi.mock('../BuildPage/flow/FlowChat/ChatMessages', () => ({ default: () => <div>Workflow messages</div> }))
vi.mock('./SaveQaLibForm', async () => {
    const React = await import('react')
    return { default: React.forwardRef(({ onMarked }: { onMarked: () => void }, ref) => {
        React.useImperativeHandle(ref, () => ({ open: mock.qa }))
        return <button onClick={onMarked}>QA saved</button>
    }) }
})
vi.mock('./AddSimilarQuestions', async () => {
    const React = await import('react')
    return { default: React.forwardRef((_, ref) => { React.useImperativeHandle(ref, () => ({ open: mock.similar })); return null }) }
})
afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    mock.permission.mockResolvedValue(true)
    mock.status.mockResolvedValue({ status: 1, is_self: true })
    mock.next.mockImplementation(({ action }: { action: string }) => Promise.resolve(action === 'next' ? { flow_id: 'flow-2', chat_id: 'chat-2', flow_type: 10 } : null))
    mock.update.mockResolvedValue({})
})
function Location() { return <output aria-label="location">{useLocation().pathname}</output> }
function setup(type = 5) {
    render(<MemoryRouter initialEntries={[`/label/chat/7/flow-1/chat-1/${type}`]}><Routes><Route path="/label/chat/:id/:fid/:cid/:type" element={<TaskAppChats />} /></Routes><Location /></MemoryRouter>)
}
it('preserves radio status payloads and assistant history loading', async () => {
    setup()
    await waitFor(() => expect(screen.getByRole('radio', { name: 'label.labeled' })).toBeEnabled())
    fireEvent.click(screen.getByRole('radio', { name: 'label.labeled' }))
    expect(mock.update).toHaveBeenCalledWith({ session_id: 'chat-1', task_id: 7, status: 2 })
    expect(mock.assistant).toHaveBeenCalledWith('flow-1', 'chat-1', { appendHistory: true, lastMsg: '' })
    expect(mock.workflow).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Assistant annotation' }))
    expect(mock.similar).toHaveBeenCalledWith('message-1', { q: 'Question', a: 'Answer' })
})
it('keeps all statuses disabled without annotation permission', async () => {
    mock.permission.mockResolvedValue(false)
    setup()
    await waitFor(() => expect(mock.status).toHaveBeenCalled())
    screen.getAllByRole('radio').forEach(radio => expect(radio).toBeDisabled())
    fireEvent.click(screen.getByRole('radio', { name: 'label.labeled' }))
    expect(mock.update).not.toHaveBeenCalled()
})
it('keeps another annotator’s completed conversation readonly', async () => {
    mock.status.mockResolvedValue({ status: 2, is_self: false })
    setup()
    await waitFor(() => expect(screen.getByRole('radio', { name: 'label.labeled' })).toHaveAttribute('aria-checked', 'true'))
    screen.getAllByRole('radio').forEach(radio => expect(radio).toBeDisabled())
})
it('marks an unlabelled workflow after QA save and preserves next-conversation routing', async () => {
    setup(10)
    await waitFor(() => expect(mock.workflow).toHaveBeenCalled())
    expect(mock.assistant).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'QA saved' }))
    expect(mock.update).toHaveBeenCalledWith({ session_id: 'chat-1', task_id: 7, status: 2 })
    await waitFor(() => expect(screen.getByRole('button', { name: 'label.nextChat' })).toBeEnabled())
    expect(screen.getByRole('button', { name: 'label.previousChat' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'label.nextChat' }))
    expect(screen.getByLabelText('location')).toHaveTextContent('/label/chat/7/flow-2/chat-2/10')
})
