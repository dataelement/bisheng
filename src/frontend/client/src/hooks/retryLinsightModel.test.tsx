import { act, renderHook } from '@testing-library/react';
import React from 'react';
// Exercise the existing model atom; this test does not introduce shared state.
// eslint-disable-next-line no-restricted-imports
import { RecoilRoot, useSetRecoilState } from 'recoil';
import request from '~/api/request';
import store from '~/store';
import { SopStatus, type LinsightInfo } from '~/store/linsight';
import { useLinsightManager } from './useLinsightManager';

jest.mock('sse.js', () => ({ SSE: class {} }));
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/hooks', () => ({ useLocalize: () => (key: string) => key }));
jest.mock('~/api/request', () => ({ __esModule: true, default: { post: jest.fn() } }));

const wrapper = ({ children }: { children: React.ReactNode }) => <RecoilRoot>{children}</RecoilRoot>;
const failedTask = {
    session_id: 'chat-1', question: 'Original question', model: '936', status: SopStatus.Stoped,
    taskError: 'Rate limited', taskErrorInfo: { error_type: 'rate_limit' },
    tasks: [], sessionSteps: [], file_list: [], history: [],
} as unknown as Omit<LinsightInfo, 'id'>;

beforeEach(() => {
    jest.clearAllMocks();
    (request.post as jest.Mock).mockResolvedValue({ data: true });
});

function mount() {
    const hook = renderHook(() => ({ ...useLinsightManager(), setModel: useSetRecoilState(store.chatModel) }), { wrapper });
    act(() => {
        hook.result.current.createLinsight('task-1', failedTask);
        hook.result.current.setModel({ id: 936, name: 'Original model', mode: 'task' });
    });
    return hook.result;
}

it('sends the model selected after failure when retrying the task', async () => {
    const result = mount();
    act(() => result.current.setModel({ id: 954, name: 'Replacement model', mode: 'task' }));
    await act(async () => { await result.current.retryConversation('task-1', 'Original question'); });
    expect(request.post).toHaveBeenCalledWith('/api/v1/linsight/workbench/continue', {
        session_version_id: 'task-1', question: 'Original question', model: '954',
    });
});

it('keeps ordinary follow-ups on the original model even when the selector changed', async () => {
    const result = mount();
    act(() => result.current.setModel({ id: 954, name: 'Replacement model', mode: 'task' }));
    await act(async () => { await result.current.continueConversation('task-1', 'Follow-up'); });
    expect(request.post).toHaveBeenCalledWith('/api/v1/linsight/workbench/continue', {
        session_version_id: 'task-1', question: 'Follow-up',
    });
});

it('preserves the task model if no current model is selected', async () => {
    const result = mount();
    act(() => result.current.setModel({ id: 0, name: '' }));
    await act(async () => { await result.current.retryConversation('task-1', 'Original question'); });
    expect(request.post).toHaveBeenCalledWith('/api/v1/linsight/workbench/continue', {
        session_version_id: 'task-1', question: 'Original question',
    });
});
