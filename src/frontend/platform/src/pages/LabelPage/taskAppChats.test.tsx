import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import TaskAppChats from './taskAppChats'

const mock = vi.hoisted(() => ({ detail: vi.fn(), permission: vi.fn(), status: vi.fn(), next: vi.fn(), update: vi.fn(), assistant: vi.fn(), workflow: vi.fn(), similar: vi.fn(), qa: vi.fn(), clear: vi.fn(), change: vi.fn(), destroy: vi.fn(), completeQa: vi.fn() }))
vi.mock('@/controllers/request', () => ({ captureAndAlertRequestErrorHoc: (p: Promise<unknown>) => p.catch(() => false) }));
vi.mock('@/controllers/API/flow', () => ({ getDeleteFlowApi: mock.detail }))
vi.mock('@/controllers/API/log', () => ({ getMarkPermissionApi: mock.permission, getMarkStatusApi: mock.status, getNextMarkChatApi: mock.next, updateMarkStatusApi: mock.update }))
vi.mock('@/components/bs-comp/chatComponent/messageStore', () => ({ MessageStoreProvider: ({ children }: { children: React.ReactNode }) => children, useMessageStore: () => ({ loadHistoryMsg: mock.assistant, loadMoreHistoryMsg: vi.fn(), changeChatId: mock.change, clearMsgs: mock.clear }) }))
vi.mock('@/pages/BuildPage/flow/FlowChat/messageStore', () => ({ MessageStoreProvider: ({ children }: { children: React.ReactNode }) => children, useMessageStore: () => ({ loadHistoryMsg: mock.workflow, loadMoreHistoryMsg: vi.fn(), changeChatId: mock.change, clearMsgs: mock.clear }) }))
vi.mock('@/store/assistantStore', () => ({ useAssistantStore: () => ({ destroy: mock.destroy }) }))
vi.mock('@/components/bs-comp/chatComponent/MessagePanne', () => ({ default: ({ onMarkClick, chat, logo }: { chat?: { name: string }; logo?: React.ReactNode; onMarkClick: (type: string, id: string, qa: { q: string; a: string }) => void }) => <div>{logo}<span>{chat?.name}</span><button onClick={() => onMarkClick('question', 'message-1', { q: 'Question', a: 'Answer' })}>Assistant annotation</button></div> }))
vi.mock('../BuildPage/flow/FlowChat/ChatMessages', () => ({ default: ({ onMarkClick, title, logo }: { title?: string; logo?: React.ReactNode; onMarkClick: (kind: string, id: string, qa: { q: string; a: string }) => void }) => <div>{logo}<span>{title}</span><button onClick={() => onMarkClick('answer', 'message-2', { q: 'Question', a: 'Answer' })}>Workflow annotation</button></div> }))
vi.mock('./SaveQaLibForm', async () => {
    const React = await import('react')
    return { default: React.forwardRef(({ onMarked }: { onMarked: (operation?: unknown) => void }, ref) => {
        const operation = React.useRef<unknown>();
        React.useImperativeHandle(ref, () => ({ open: (...args: unknown[]) => { mock.qa(...args); operation.current = args[2]; mock.completeQa.mockImplementation(() => onMarked(args[2])); }, close: vi.fn() }))
        return <button onClick={() => onMarked(operation.current)}>QA saved</button>
    }) }
})
vi.mock('./AddSimilarQuestions', async () => {
    const React = await import('react')
    return { default: React.forwardRef((_, ref) => { React.useImperativeHandle(ref, () => ({ open: mock.similar, close: vi.fn() })); return null }) }
})
afterEach(cleanup)
beforeEach(() => {
    vi.clearAllMocks()
    mock.detail.mockResolvedValue({ flow_name: 'Weather assistant', flow_logo: '/test-app.png' })
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
    expect(mock.similar).toHaveBeenCalledWith('message-1', { q: 'Question', a: 'Answer' }, expect.objectContaining({ taskId: '7', conversationId: 'chat-1', sourceMessageId: 'message-1' }))
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
    fireEvent.click(screen.getByRole('button', { name: 'Workflow annotation' }))
    fireEvent.click(screen.getByRole('button', { name: 'QA saved' }))
    expect(mock.update).toHaveBeenCalledWith({ session_id: 'chat-1', task_id: 7, status: 2 })
    await waitFor(() => expect(screen.getByRole('button', { name: 'label.nextChat' })).toBeEnabled())
    expect(screen.getByRole('button', { name: 'label.previousChat' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'label.nextChat' }))
    expect(screen.getByLabelText('location')).toHaveTextContent('/label/chat/7/flow-2/chat-2/10')
})


it('does not change the next conversation when an earlier QA completion arrives', async () => {
    setup(10);
    await waitFor(() => expect(screen.getByRole('radio', { name: 'label.unlabeled' })).toHaveAttribute('aria-checked', 'true'));
    fireEvent.click(screen.getByRole('button', { name: 'Workflow annotation' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'label.nextChat' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'label.nextChat' }));
    await waitFor(() => expect(mock.workflow).toHaveBeenCalledWith('flow-2', 'chat-2', expect.any(Object)));
    await act(async () => { await mock.completeQa(); });
    await waitFor(() => expect(mock.update).toHaveBeenCalledWith({ session_id: 'chat-1', task_id: 7, status: 2 }));
    expect(screen.getByRole('radio', { name: 'label.unlabeled' })).toHaveAttribute('aria-checked', 'true');
});

it('does not optimistically mark completion after a rejected status write', async () => {
    setup(10);
    await waitFor(() => expect(mock.workflow).toHaveBeenCalled());
    mock.update.mockRejectedValueOnce(new Error('status failed'));
    fireEvent.click(screen.getByRole('radio', { name: 'label.labeled' }));
    await waitFor(() => expect(mock.update).toHaveBeenCalled());
    expect(screen.getByRole('radio', { name: 'label.unlabeled' })).toHaveAttribute('aria-checked', 'true');
});

it('does not apply an old A completion to a newly opened A after A → B → A', async () => {
    mock.next.mockImplementation(({ action, chat_id }: { action: string; chat_id: string }) => Promise.resolve(
        action === 'next' && chat_id === 'chat-1' ? { flow_id: 'flow-2', chat_id: 'chat-2', flow_type: 10 }
            : action === 'prev' && chat_id === 'chat-2' ? { flow_id: 'flow-1', chat_id: 'chat-1', flow_type: 10 } : null));
    setup(10);
    await waitFor(() => expect(screen.getByRole('radio', { name: 'label.unlabeled' })).toHaveAttribute('aria-checked', 'true'));
    fireEvent.click(screen.getByRole('button', { name: 'Workflow annotation' }));
    const completeOldA = mock.completeQa.getMockImplementation();
    await waitFor(() => expect(screen.getByRole('button', { name: 'label.nextChat' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'label.nextChat' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'label.previousChat' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'label.previousChat' }));
    await waitFor(() => expect(screen.getByLabelText('location')).toHaveTextContent('/label/chat/7/flow-1/chat-1/10'));
    await act(async () => { await completeOldA?.(); });
    expect(mock.update).toHaveBeenCalledWith({ session_id: 'chat-1', task_id: 7, status: 2 });
    expect(screen.getByRole('radio', { name: 'label.unlabeled' })).toHaveAttribute('aria-checked', 'true');
});

it.each([5, 10])('restores application name and avatar from session metadata for type %s', async type => {
    setup(type);
    expect(await screen.findByText('Weather assistant')).toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('src', '/test-app.png');
    expect(mock.detail).toHaveBeenCalledWith('chat-1');
});

it('ignores application metadata arriving after the next conversation has opened', async () => {
    let finishOld: (value: { flow_name: string; flow_logo: string }) => void = () => undefined;
    mock.detail.mockImplementationOnce(() => new Promise(resolve => { finishOld = resolve; }))
        .mockResolvedValueOnce({ flow_name: 'Next application', flow_logo: '/next.png' });
    setup(10);
    await waitFor(() => expect(screen.getByRole('button', { name: 'label.nextChat' })).toBeEnabled());
    fireEvent.click(screen.getByRole('button', { name: 'label.nextChat' }));
    expect(await screen.findByText('Next application')).toBeInTheDocument();
    await act(async () => { finishOld({ flow_name: 'Old application', flow_logo: '/old.png' }); });
    expect(screen.queryByText('Old application')).not.toBeInTheDocument();
    expect(screen.getByRole('img')).toHaveAttribute('src', '/next.png');
});
