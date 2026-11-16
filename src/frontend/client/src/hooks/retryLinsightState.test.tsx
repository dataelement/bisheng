import { act, renderHook, waitFor } from '@testing-library/react';
import React from 'react';
// Exercise the existing task store; no new shared state is introduced.
// eslint-disable-next-line no-restricted-imports
import { RecoilRoot } from 'recoil';
import { continueLinsight, getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import { SopStatus, type LinsightInfo } from '~/store/linsight';
import { useLinsightManager } from './useLinsightManager';
import { useLinsightWebSocket } from './Websocket';

jest.mock('sse.js', () => ({ SSE: class {} }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/hooks/inviteQuotaRefresh', () => ({ refreshInviteQuota: jest.fn() }));
jest.mock('~/api/linsight', () => ({
    continueLinsight: jest.fn(), getLinsightSessionVersionList: jest.fn(), getLinsightTaskList: jest.fn(),
    startLinsight: jest.fn(), userInputLinsightEvent: jest.fn(), userStopLinsightEvent: jest.fn(),
}));

function deferred<T>() {
    let resolve!: (value: T) => void;
    let reject!: (error: Error) => void;
    const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
    return { promise, resolve, reject };
}
class SocketDouble {
    static OPEN = 1;
    static instances: SocketDouble[] = [];
    readyState = 0;
    onopen?: () => void;
    onmessage?: (event: { data: string }) => void;
    onclose?: () => void;
    constructor() { SocketDouble.instances.push(this); }
    open() { this.readyState = 1; this.onopen?.(); }
    close() { this.readyState = 3; }
    message(event_type: string, data: object) { this.onmessage?.({ data: JSON.stringify({ event_type, data }) }); }
}
const originalSocket = globalThis.WebSocket;
const wrapper = ({ children }: { children: React.ReactNode }) => <RecoilRoot>{children}</RecoilRoot>;
const failedVersion = {
    id: 'task-1', status: 'failed',
    output_result: { error_message: 'Previous model failed', error_type: 'service_unavailable' },
};
function mount() {
    const hook = renderHook(() => {
        const manager = useLinsightManager();
        useLinsightWebSocket('task-1');
        return manager;
    }, { wrapper });
    act(() => hook.result.current.createLinsight('task-1', {
        session_id: 'chat-1', question: 'Original question', status: SopStatus.Stoped,
        taskError: 'Previous model failed', taskErrorInfo: { error_type: 'service_unavailable' },
        output_result: failedVersion.output_result, execute_feedback: 'Old feedback', queueCount: 3,
        tasks: [], sessionSteps: [], file_list: [], history: [],
    } as unknown as Omit<LinsightInfo, 'id'>));
    return hook;
}
beforeEach(() => {
    jest.clearAllMocks();
    SocketDouble.instances = [];
    globalThis.WebSocket = SocketDouble as unknown as typeof WebSocket;
    (continueLinsight as jest.Mock).mockResolvedValue({});
    (getLinsightSessionVersionList as jest.Mock).mockResolvedValue([{ id: 'task-1', status: 'in_progress' }]);
    (getLinsightTaskList as jest.Mock).mockResolvedValue([]);
});
afterEach(() => { globalThis.WebSocket = originalSocket; });

it('opens the new round only after retry acceptance and receives clarification without a refresh', async () => {
    const acceptance = deferred<object>();
    (continueLinsight as jest.Mock).mockReturnValue(acceptance.promise);
    const { result } = mount();
    let retry!: Promise<void>;
    act(() => { retry = result.current.continueConversation('task-1', 'Original question', '932'); });
    expect(SocketDouble.instances).toHaveLength(0);
    expect(result.current.getLinsight('task-1')!.history).toHaveLength(0);

    await act(async () => { acceptance.resolve({}); await retry; });
    expect(SocketDouble.instances).toHaveLength(1);
    await act(async () => SocketDouble.instances[0].open());
    act(() => SocketDouble.instances[0].message('user_input', { task_id: 'task-1', params: ['Please confirm'] }));
    const info = result.current.getLinsight('task-1')!;
    expect(info.status).toBe(SopStatus.Running);
    expect(info.taskError).toBe('');
    expect(info.taskErrorInfo).toBeUndefined();
    expect(info.execute_feedback).toBeNull();
    expect(info.queueCount).toBe(0);
    expect(info.sessionSteps).toEqual([expect.objectContaining({ step_type: 'call_user_input', params: ['Please confirm'] })]);
    expect(info.history).toEqual([expect.objectContaining({ taskError: 'Previous model failed' })]);
});

it.each(['versions', 'tasks'])('ignores a previous round reconciliation delayed in %s until after retry acceptance', async (stage) => {
    const versions = deferred<typeof failedVersion[]>();
    const tasks = deferred<[]>();
    (getLinsightSessionVersionList as jest.Mock).mockReturnValue(stage === 'versions' ? versions.promise : Promise.resolve([failedVersion]));
    (getLinsightTaskList as jest.Mock).mockReturnValue(stage === 'tasks' ? tasks.promise : Promise.resolve([]));
    const { result } = mount();
    let reconciliation!: Promise<boolean>;
    act(() => { reconciliation = result.current.reconcileLinsightFromServer('task-1'); });
    await waitFor(() => expect(stage === 'versions' ? getLinsightSessionVersionList : getLinsightTaskList).toHaveBeenCalled());
    await act(async () => { await result.current.continueConversation('task-1', 'Original question', '932'); });
    await act(async () => {
        versions.resolve([failedVersion]); tasks.resolve([]);
        await reconciliation;
    });
    expect(result.current.getLinsight('task-1')!.status).toBe(SopStatus.Running);
    expect(result.current.getLinsight('task-1')!.taskError).toBe('');
});

it('ignores a retired socket error while still displaying errors from the current retry', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
    const { result } = mount();
    await act(async () => { await result.current.continueConversation('task-1', 'Original question', '932'); });
    const oldSocket = SocketDouble.instances[0];
    await act(async () => oldSocket.open());
    act(() => oldSocket.message('error_message', { error: 'First retry failed', error_type: 'network_timeout' }));
    expect(result.current.getLinsight('task-1')!.taskError).toBe('First retry failed');
    await act(async () => { await result.current.continueConversation('task-1', 'Original question', '954'); });
    act(() => oldSocket.message('error_message', { error: 'Late first retry failure' }));
    expect(result.current.getLinsight('task-1')!.status).toBe(SopStatus.Running);
    expect(result.current.getLinsight('task-1')!.taskError).toBe('');
    act(() => SocketDouble.instances[1].message('error_message', { error: 'Current retry failed', error_type: 'rate_limit' }));
    expect(result.current.getLinsight('task-1')!.status).toBe(SopStatus.Stoped);
    expect(result.current.getLinsight('task-1')!.taskErrorInfo?.error_type).toBe('rate_limit');
});

it('keeps round history unchanged and opens no socket when the retry request is rejected', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
    (continueLinsight as jest.Mock).mockRejectedValue(new Error('Dispatch unavailable'));
    const { result } = mount();
    await act(async () => { await result.current.continueConversation('task-1', 'Original question', '932'); });
    expect(SocketDouble.instances).toHaveLength(0);
    expect(result.current.getLinsight('task-1')!.history).toHaveLength(0);
    expect(result.current.getLinsight('task-1')!.status).toBe(SopStatus.Stoped);
    expect(result.current.getLinsight('task-1')!.taskError).toContain('Dispatch unavailable');
    expect(result.current.getLinsight('task-1')!.taskErrorInfo).toBeUndefined();
    expect(result.current.getLinsight('task-1')!.output_result).toBeNull();
});

it('recovers a retry that completed before its new socket opened', async () => {
    (getLinsightSessionVersionList as jest.Mock).mockResolvedValue([{
        id: 'task-1', status: 'completed', output_result: { answer: 'Replacement model answered', final_files: [] },
    }]);
    const { result } = mount();
    await act(async () => { await result.current.continueConversation('task-1', 'Original question', '932'); });
    await act(async () => SocketDouble.instances[0].open());
    expect(result.current.getLinsight('task-1')!.status).toBe(SopStatus.completed);
    expect(result.current.getLinsight('task-1')!.output_result.answer).toBe('Replacement model answered');
    expect(result.current.getLinsight('task-1')!.taskError).toBe('');
});

it('submits only one continuation when a caller retries twice before acceptance', async () => {
    const acceptance = deferred<object>();
    (continueLinsight as jest.Mock).mockReturnValue(acceptance.promise);
    const { result } = mount();
    let first!: Promise<void>, second!: Promise<void>;
    act(() => {
        first = result.current.continueConversation('task-1', 'Original question', '932');
        second = result.current.continueConversation('task-1', 'Original question', '932');
    });
    expect(continueLinsight).toHaveBeenCalledTimes(1);
    await act(async () => { acceptance.resolve({}); await Promise.all([first, second]); });
    expect(result.current.getLinsight('task-1')!.status).toBe(SopStatus.Running);
    expect(result.current.getLinsight('task-1')!.history).toHaveLength(1);
    expect(SocketDouble.instances).toHaveLength(1);
});

it('allows another retry after its request was rejected', async () => {
    jest.spyOn(console, 'error').mockImplementation(() => undefined);
    (continueLinsight as jest.Mock).mockRejectedValueOnce(new Error('Dispatch unavailable'));
    const { result } = mount();
    await act(async () => { await result.current.continueConversation('task-1', 'Original question', '932'); });
    await act(async () => { await result.current.continueConversation('task-1', 'Original question', '954'); });
    expect(result.current.getLinsight('task-1')!.status).toBe(SopStatus.Running);
    expect(result.current.getLinsight('task-1')!.taskError).toBe('');
    expect(SocketDouble.instances).toHaveLength(1);
});
