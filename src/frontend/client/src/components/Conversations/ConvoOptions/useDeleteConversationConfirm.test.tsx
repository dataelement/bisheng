import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook } from '@testing-library/react';
import type { ReactNode } from 'react';
import { stopConversationRun } from '~/api/runApi';
import { useRunStore } from '~/store/runStore';
import { STOP_BEFORE_DELETE_TIMEOUT_MS, useDeleteConversationConfirm } from './useDeleteConversationConfirm';

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
    useRunStore.setState({ conversations: {} });
});

afterEach(() => {
    jest.useRealTimers();
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

test('the delete is sent only after the stop request has answered', async () => {
    mockConfirm.mockResolvedValue(true);
    const order: string[] = [];
    let answerStop: () => void = () => undefined;
    mockStop.mockImplementation(
        () =>
            new Promise((resolve) => {
                answerStop = () => {
                    order.push('stop answered');
                    resolve({ run_id: 'r1', status: 'stopping', unread_messages: [] });
                };
            }),
    );
    mockMutate.mockImplementation(() => order.push('delete'));
    const { result } = renderHook(() => useDeleteConversationConfirm(), { wrapper });

    let pending: Promise<void> = Promise.resolve();
    await act(async () => {
        pending = result.current({ conversationId: 'c1', title: 't', retainView: jest.fn() });
        await Promise.resolve();
    });
    expect(mockMutate).not.toHaveBeenCalled();

    await act(async () => {
        answerStop();
        await pending;
    });
    expect(order).toEqual(['stop answered', 'delete']);
});

test('a stop request that never answers still lets the delete go ahead after the timeout', async () => {
    jest.useFakeTimers();
    mockConfirm.mockResolvedValue(true);
    mockStop.mockReturnValue(new Promise(() => undefined));
    const { result } = renderHook(() => useDeleteConversationConfirm(), { wrapper });

    let pending: Promise<void> = Promise.resolve();
    await act(async () => {
        pending = result.current({ conversationId: 'c1', title: 't', retainView: jest.fn() });
        await Promise.resolve();
    });
    expect(mockMutate).not.toHaveBeenCalled();

    await act(async () => {
        jest.advanceTimersByTime(STOP_BEFORE_DELETE_TIMEOUT_MS);
        await pending;
    });
    expect(mockMutate).toHaveBeenCalledTimes(1);
});

test('a successful delete drops the run state of the conversation', async () => {
    mockConfirm.mockResolvedValue(true);
    mockStop.mockResolvedValue({ run_id: 'r1', status: 'stopping', unread_messages: [] });
    mockMutate.mockImplementation((_vars, options: { onSuccess: () => void }) => options.onSuccess());
    useRunStore.getState().applySendResult('c1', { run_id: 'r1', disposition: 'started', message_id: 'm1' });
    useRunStore.getState().applySendResult('c2', { run_id: 'r2', disposition: 'started', message_id: 'm2' });
    const retainView = jest.fn();
    const { result } = renderHook(() => useDeleteConversationConfirm(), { wrapper });

    await act(async () => {
        await result.current({ conversationId: 'c1', title: 't', retainView });
    });

    expect(useRunStore.getState().conversations.c1).toBeUndefined();
    expect(useRunStore.getState().conversations.c2).toBeDefined();
    expect(retainView).toHaveBeenCalledTimes(1);
});

test('a failed delete keeps the run state of the conversation', async () => {
    mockConfirm.mockResolvedValue(true);
    mockStop.mockResolvedValue({ run_id: 'r1', status: 'idle', unread_messages: [] });
    mockMutate.mockImplementation((_vars, options: { onError: (e: unknown) => void }) => options.onError(new Error('x')));
    useRunStore.getState().applySendResult('c1', { run_id: 'r1', disposition: 'started', message_id: 'm1' });
    const { result } = renderHook(() => useDeleteConversationConfirm(), { wrapper });

    await act(async () => {
        await result.current({ conversationId: 'c1', title: 't', retainView: jest.fn() });
    });

    expect(useRunStore.getState().conversations.c1).toBeDefined();
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
