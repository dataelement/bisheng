import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { stopConversationRun } from '~/api/runApi';
import { useDeleteConversationConfirm } from './useDeleteConversationConfirm';

const mockConfirm = jest.fn();
const mockMutate = jest.fn();

jest.mock('~/api/runApi', () => ({ stopConversationRun: jest.fn() }));
jest.mock('~/api/request', () => ({ showApiError: jest.fn() }));
jest.mock('react-router-dom', () => ({ useNavigate: () => jest.fn(), useParams: () => ({ conversationId: 'other' }) }));
jest.mock('~/Providers', () => ({ useConfirm: () => mockConfirm }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key, useNewConvo: () => ({ newConversation: jest.fn() }) }));
jest.mock('~/hooks/queries/data-provider', () => ({ useDeleteConversationMutation: () => ({ mutate: mockMutate }) }));

const mockStop = stopConversationRun as jest.MockedFunction<typeof stopConversationRun>;

function wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
    mockConfirm.mockReset();
    mockMutate.mockReset();
    mockStop.mockReset();
});

test('stops the run of the conversation before deleting it (F004)', async () => {
    mockConfirm.mockResolvedValue(true);
    mockStop.mockResolvedValue({ run_id: 'r1', status: 'stopping', unread_messages: [] });
    const { result } = renderHook(() => useDeleteConversationConfirm(), { wrapper });

    await act(async () => {
        await result.current({ conversationId: 'c1', title: 't', retainView: jest.fn() });
    });

    expect(mockStop).toHaveBeenCalledWith('c1');
    expect(mockMutate).toHaveBeenCalledWith(expect.objectContaining({ conversationId: 'c1' }), expect.anything());
});

test('a failed stop does not keep the conversation from being deleted', async () => {
    mockConfirm.mockResolvedValue(true);
    mockStop.mockRejectedValue(new Error('network'));
    const { result } = renderHook(() => useDeleteConversationConfirm(), { wrapper });

    await act(async () => {
        await result.current({ conversationId: 'c1', title: 't', retainView: jest.fn() });
    });

    expect(mockMutate).toHaveBeenCalledTimes(1);
});

test('nothing is stopped when the user cancels', async () => {
    mockConfirm.mockResolvedValue(false);
    const { result } = renderHook(() => useDeleteConversationConfirm(), { wrapper });

    await act(async () => {
        await result.current({ conversationId: 'c1', title: 't', retainView: jest.fn() });
    });

    expect(mockStop).not.toHaveBeenCalled();
    expect(mockMutate).not.toHaveBeenCalled();
});
