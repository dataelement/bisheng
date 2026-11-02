import { render, screen } from '@testing-library/react';
import type { ChatMessageType } from '~/@types/chat';
import { getChatHistoryApi } from '~/api/apps';
import request from '~/api/request';
import MessageBs from './MessageBs';

jest.mock('~/api/request', () => ({ __esModule: true, default: { get: jest.fn() } }));
jest.mock('react-router-dom', () => ({ useParams: () => ({}) }));
jest.mock('~/hooks/useLocalize', () => ({ __esModule: true, default: () => (key: string) => key }));
jest.mock('~/hooks/useMessageSelection', () => ({ useMessageSelection: () => ({ isActiveForChat: () => false }) }));
jest.mock('~/components/Chat/MessageSelection', () => ({ ExportSelectionButton: () => null, MessageCheckbox: () => null }));
jest.mock('~/components/Chat/Messages/Content/Markdown', () => ({ __esModule: true, default: ({ content }: { content: string }) => <p>{content}</p> }));
jest.mock('~/components/Chat/Messages/Content/CitationReferencesDrawer', () => ({ __esModule: true, default: () => null }));
jest.mock('~/components/ui/icon/Loading', () => ({ LoadingIcon: () => <span>loading</span> }));
jest.mock('./MessageButtons', () => ({ __esModule: true, default: () => null }));
jest.mock('./AppChatFileList', () => ({ AppChatFileList: () => null }));
jest.mock('~/utils', () => ({ cn: (...parts: string[]) => parts.filter(Boolean).join(' '), copyText: jest.fn(), formatStrTime: () => '', generateUUID: () => 'id' }));

const baseMessage: ChatMessageType = { message: 'partial answer', files: [], end: true,
    isSend: false, chatKey: '', user_name: '', create_time: '', update_time: '' };

test('stopped answer renders a persistent status below its partial content', () => {
    render(<MessageBs logo={null} title="Application" data={{ ...baseMessage, stopped: true }} />);
    expect(screen.getByText('partial answer')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('appChat.stopped');
    expect(screen.queryByText('loading')).toBeNull();
});

test('reasoning-only stop displays its content and stopped state', () => {
    render(<MessageBs logo={null} title="Application" data={{ ...baseMessage, message: '', reasoning_log: 'partial thinking', stopped: true }} />);
    expect(screen.getByText('partial thinking')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('appChat.stopped');
    expect(screen.queryByText('com_bs_reasoning_done')).toBeNull();
});

test('normal completed answer renders with its completion state', () => {
    render(<MessageBs logo={null} title="Application" data={baseMessage} />);
    expect(screen.getByText('partial answer')).toBeVisible();
    expect(screen.queryByRole('status')).toBeNull();
});

test('reopening assistant history restores the backend stopped marker', async () => {
    jest.mocked(request.get).mockResolvedValue({ status_code: 200, data: [
        { id: 42, is_bot: true, category: 'answer', message: 'stored partial', remark: 'break_answer' },
    ] });
    const history = await getChatHistoryApi({ flowId: 'flow', chatId: 'chat', flowType: '5' });
    render(<MessageBs logo={null} title="Application" data={history[0]} />);
    expect(screen.getByText('stored partial')).toBeVisible();
    expect(screen.getByRole('status')).toHaveTextContent('appChat.stopped');
});
