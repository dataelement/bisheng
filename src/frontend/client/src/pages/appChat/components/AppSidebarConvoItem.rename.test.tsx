import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AppSidebarConvoItem } from './AppSidebarConvoItem';

const mockRename = jest.fn();
const mockRefreshed = jest.fn();

jest.mock('recoil', () => ({ useSetRecoilState: () => jest.fn() }));
jest.mock('@tanstack/react-query', () => ({ useQueryClient: () => ({}) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/Providers', () => ({
    useToastContext: () => ({ showToast: jest.fn() }),
    useConfirm: () => jest.fn(),
}));
jest.mock('~/hooks/queries/data-provider', () => ({
    useUpdateConversationMutation: () => ({ mutateAsync: mockRename }),
    useDeleteConversationMutation: () => ({ mutate: jest.fn() }),
}));
jest.mock('~/pages/appChat/store/atoms', () => ({ chatsState: 'chats', runningState: 'running' }));
jest.mock('~/pages/appChat/useWebsocket', () => ({ closeAppChatWebSocket: jest.fn() }));
jest.mock('~/types/chat', () => ({ QueryKeys: { messages: 'messages' } }));
jest.mock('~/utils', () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(' ') }));

const conversation = {
    id: 'chat', title: 'Original title', flowId: 'app', flowType: 5, createdAt: '', updatedAt: '',
};

function openEditor() {
    const view = render(
        <>
            <div data-testid="blank-space" />
            <AppSidebarConvoItem
                compact
                conv={conversation}
                isActive
                onClick={jest.fn()}
                onDeleteSuccess={jest.fn()}
                onRenameSuccess={mockRefreshed}
            />
        </>,
    );
    fireEvent.doubleClick(screen.getByRole('button', { name: conversation.title }));
    const input = screen.getByRole<HTMLInputElement>('textbox', { name: 'com_ui_rename com_ui_chat' });
    return { ...view, input };
}

beforeEach(() => {
    mockRename.mockReset().mockResolvedValue(undefined);
    mockRefreshed.mockClear();
});

it('selects the title and saves once when clicking blank space, even if the row closes during the save', async () => {
    const user = userEvent.setup();
    let finishSave!: () => void;
    mockRename.mockImplementationOnce(() => new Promise<void>((resolve) => { finishSave = resolve; }));
    const { input, unmount } = openEditor();
    expect(input).toHaveFocus();
    expect(input.selectionStart).toBe(0);
    expect(input.selectionEnd).toBe(conversation.title.length);

    await user.keyboard('Renamed title');
    await user.click(screen.getByTestId('blank-space'));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    expect(mockRename).toHaveBeenCalledTimes(1);
    expect(mockRename).toHaveBeenCalledWith({ conversationId: 'chat', title: 'Renamed title', flowId: 'app', flowType: 5 });

    unmount();
    await act(async () => { finishSave(); });
    expect(mockRefreshed).toHaveBeenCalledWith('chat', 'Renamed title');
});

it.each(['Enter', 'Save button', 'Tab away from Save'])('commits once with %s', async (method) => {
    const user = userEvent.setup();
    const { input } = openEditor();
    fireEvent.change(input, { target: { value: 'Renamed title' } });

    if (method === 'Enter') {
        fireEvent.keyDown(input, { key: 'Enter', isComposing: true });
        expect(mockRename).not.toHaveBeenCalled();
        await user.keyboard('{Enter}');
    } else {
        await user.tab();
        const save = screen.getByRole('button', { name: 'com_ui_submit com_ui_rename' });
        expect(save).toHaveFocus();
        expect(mockRename).not.toHaveBeenCalled();
        if (method === 'Save button') await user.click(save);
        else await user.tab();
    }

    expect(mockRename).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
});

it.each([['Escape', 'Discard this'], ['blur', '   '], ['blur', conversation.title]])('restores the title on %s with %p', async (key, title) => {
    const user = userEvent.setup();
    const { input } = openEditor();
    fireEvent.change(input, { target: { value: title } });
    if (key === 'Escape') await user.keyboard('{Escape}');
    else await user.click(screen.getByTestId('blank-space'));
    expect(mockRename).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: conversation.title })).toBeVisible();
});
