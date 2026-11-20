/**
 * F004 design §7 items 9 and 15: which sends ask the deep-research invite
 * quota, and the retry of a failed deep-research turn.
 */
import { act, renderHook } from '@testing-library/react';
import { useRunStore, type RunEvent } from '~/store/runStore';
import { useChatSendActions, type UseChatSendActionsOptions } from './useChatSendActions';

const CID = 'c1';
let entry = 0;
const emit = (event: Record<string, unknown>, cid = CID) =>
    act(() => {
        useRunStore.getState().applyEvent(cid, { run_id: 'r1', data: {}, ...event } as RunEvent, `5-${++entry}`);
    });
const ask = () => emit({ type: 'ask_user', data: { call_id: 'q1', questions: [{ question: 'Which one?' }] } });

function setup(overrides: Partial<UseChatSendActionsOptions> = {}) {
    const sendMessage = jest.fn().mockResolvedValue(true);
    const allowInviteSend = jest.fn().mockReturnValue(true);
    const setInputText = jest.fn();
    const options: UseChatSendActionsOptions = {
        taskMode: true,
        canUseTaskMode: true,
        conversationId: CID,
        sendMessage,
        allowInviteSend,
        composerIdentity: CID,
        composerIdentityRef: { current: CID },
        setInputText,
        ...overrides,
    };
    const view = renderHook(() => useChatSendActions(options));
    return { ...view, sendMessage, allowInviteSend, setInputText, options };
}

beforeEach(() => {
    entry = 0;
    act(() => useRunStore.setState({ conversations: {} }));
});

describe('handleSend and the invite quota (item 9)', () => {
    it('asks the quota for a new deep-research request and does not send when it says no', async () => {
        const { result, sendMessage, allowInviteSend, setInputText } = setup();
        allowInviteSend.mockReturnValue(false);
        let accepted: unknown;
        await act(async () => { accepted = await result.current.handleSend('research this'); });
        expect(allowInviteSend).toHaveBeenCalledTimes(1);
        expect(accepted).toBe(false);
        expect(sendMessage).not.toHaveBeenCalled();
        expect(setInputText).not.toHaveBeenCalled();
    });

    it('sends a new deep-research request the quota allows and clears the draft', async () => {
        const { result, sendMessage, allowInviteSend, setInputText } = setup();
        await act(async () => { await result.current.handleSend('research this', [{ name: 'a.txt' }]); });
        expect(allowInviteSend).toHaveBeenCalledTimes(1);
        expect(sendMessage).toHaveBeenCalledWith('research this', [{ name: 'a.txt' }], { taskMode: true });
        expect(setInputText).toHaveBeenCalledWith('');
    });

    it('does not ask the quota for the answer to the question a run waits on', async () => {
        emit({ type: 'run_started' });
        ask();
        const { result, sendMessage, allowInviteSend } = setup();
        // Out of quota: a new request would be refused, the answer must still go out.
        allowInviteSend.mockReturnValue(false);
        let accepted: unknown;
        await act(async () => { accepted = await result.current.handleSend('the second one'); });
        expect(allowInviteSend).not.toHaveBeenCalled();
        expect(sendMessage).toHaveBeenCalledWith('the second one', undefined, { taskMode: true });
        expect(accepted).toBe(true);
    });

    it('still asks the quota for a message sent while the run is working, and after the question was answered', async () => {
        emit({ type: 'run_started' });
        const { result, allowInviteSend } = setup();
        await act(async () => { await result.current.handleSend('change step 3'); });
        expect(allowInviteSend).toHaveBeenCalledTimes(1);
        ask();
        emit({ type: 'ask_user_answered', data: { call_id: 'q1' } });
        await act(async () => { await result.current.handleSend('one more thing'); });
        expect(allowInviteSend).toHaveBeenCalledTimes(2);
    });

    it('does not let a question pending in another conversation skip the quota', async () => {
        emit({ type: 'run_started' }, 'other');
        emit({ type: 'ask_user', data: { call_id: 'q1', questions: [{ question: '?' }] } }, 'other');
        const { result, sendMessage, allowInviteSend } = setup();
        allowInviteSend.mockReturnValue(false);
        await act(async () => { await result.current.handleSend('research this'); });
        expect(allowInviteSend).toHaveBeenCalledTimes(1);
        expect(sendMessage).not.toHaveBeenCalled();
    });

    it('never asks the quota for an ordinary turn', async () => {
        const { result, sendMessage, allowInviteSend } = setup({ taskMode: false });
        await act(async () => { await result.current.handleSend('hello'); });
        expect(allowInviteSend).not.toHaveBeenCalled();
        expect(sendMessage).toHaveBeenCalledWith('hello', undefined, { taskMode: false });
    });

    it('keeps the draft when the send is refused or the composer moved on', async () => {
        const refused = setup();
        refused.sendMessage.mockResolvedValue(false);
        await act(async () => { await refused.result.current.handleSend('research this'); });
        expect(refused.setInputText).not.toHaveBeenCalled();

        const moved = setup({ composerIdentityRef: { current: 'another-draft' } });
        await act(async () => { await moved.result.current.handleSend('research this'); });
        expect(moved.setInputText).not.toHaveBeenCalled();
    });
});

describe('handleRetryTaskTurn (item 15)', () => {
    it('sends the question again as a deep-research message and leaves the draft alone', async () => {
        // The composer toggle is off: the retry is still a deep-research request.
        const { result, sendMessage, setInputText } = setup({ taskMode: false });
        let accepted: unknown;
        await act(async () => { accepted = await result.current.handleRetryTaskTurn('  compare the three quotes  '); });
        expect(sendMessage).toHaveBeenCalledTimes(1);
        expect(sendMessage).toHaveBeenCalledWith('compare the three quotes', null, { taskMode: true });
        expect(accepted).toBe(true);
        expect(setInputText).not.toHaveBeenCalled();
    });

    it('goes through the invite quota like any new deep-research request', async () => {
        const { result, sendMessage, allowInviteSend } = setup();
        allowInviteSend.mockReturnValue(false);
        let accepted: unknown;
        await act(async () => { accepted = await result.current.handleRetryTaskTurn('q'); });
        expect(allowInviteSend).toHaveBeenCalledTimes(1);
        expect(accepted).toBe(false);
        expect(sendMessage).not.toHaveBeenCalled();
    });

    it.each([
        ['the run is working', () => emit({ type: 'run_started' })],
        ['the run waits for an answer', () => { emit({ type: 'run_started' }); ask(); }],
    ])('does not send while %s', async (_name, arrange) => {
        arrange();
        const { result, sendMessage, allowInviteSend } = setup();
        let accepted: unknown;
        await act(async () => { accepted = await result.current.handleRetryTaskTurn('q'); });
        expect(accepted).toBe(false);
        expect(sendMessage).not.toHaveBeenCalled();
        expect(allowInviteSend).not.toHaveBeenCalled();
    });

    it('sends again once the previous run has ended', async () => {
        emit({ type: 'run_started' });
        emit({ type: 'run_failed', data: { code: 500, reason: 'x', detail: '' } });
        const { result, sendMessage } = setup();
        await act(async () => { await result.current.handleRetryTaskTurn('q'); });
        expect(sendMessage).toHaveBeenCalledWith('q', null, { taskMode: true });
    });

    it.each([
        ['the role may not use deep research', { canUseTaskMode: false }, 'q'],
        ['the turn has no question', {}, '   '],
    ])('does nothing when %s', async (_name, overrides, question) => {
        const { result, sendMessage } = setup(overrides);
        let accepted: unknown;
        await act(async () => { accepted = await result.current.handleRetryTaskTurn(question); });
        expect(accepted).toBe(false);
        expect(sendMessage).not.toHaveBeenCalled();
    });

    it('reports a refused send', async () => {
        const { result, sendMessage } = setup();
        sendMessage.mockResolvedValue(false);
        let accepted: unknown;
        await act(async () => { accepted = await result.current.handleRetryTaskTurn('q'); });
        expect(accepted).toBe(false);
    });
});
