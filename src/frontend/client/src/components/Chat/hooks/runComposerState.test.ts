/**
 * F004 design §7 item 8: the input box placeholder after the user stopped a run.
 * Items 1 and 6: unread messages given back go into the input box.
 */
import { act, renderHook } from '@testing-library/react';
import { useRunStore, type RunEvent } from '~/store/runStore';
import { useState } from 'react';
import { composerPlaceholder, useReturnedDraft, useRunStopped } from './runComposerState';

let entry = 0;
const emit = (type: string, cid = 'c1', runId = 'r1') =>
    act(() => {
        useRunStore.getState().applyEvent(cid, { type, run_id: runId, data: {} } as RunEvent, `7-${++entry}`);
    });

beforeEach(() => {
    entry = 0;
    act(() => useRunStore.setState({ conversations: {} }));
});

describe('useRunStopped', () => {
    it('is true from the stop until the next run starts', () => {
        const { result } = renderHook(() => useRunStopped('c1'));
        expect(result.current).toBe(false);
        emit('run_started');
        expect(result.current).toBe(false);
        emit('run_stopped');
        expect(result.current).toBe(true);
        emit('run_started', 'c1', 'r2');
        expect(result.current).toBe(false);
    });

    it.each(['run_finished', 'run_failed'])('is false after %s', (terminal) => {
        const { result } = renderHook(() => useRunStopped('c1'));
        emit('run_started');
        emit(terminal);
        expect(result.current).toBe(false);
    });

    it('does not read another conversation or a draft', () => {
        emit('run_started');
        emit('run_stopped');
        expect(renderHook(() => useRunStopped('other')).result.current).toBe(false);
        expect(renderHook(() => useRunStopped('')).result.current).toBe(false);
    });
});

describe('composerPlaceholder', () => {
    const t = (key: string) => key;
    const base = { runAwaitingAnswer: false, runStopped: false, taskMode: false };

    it('keeps the input default for an ordinary idle conversation', () => {
        expect(composerPlaceholder(t, base)).toBeUndefined();
    });

    it('says the box takes messages while a run is going on, over the mode placeholder', () => {
        expect(composerPlaceholder(t, { ...base, runTakesMessages: true })).toBe('runComposer.runningPlaceholder');
        expect(composerPlaceholder(t, { ...base, runTakesMessages: true, taskMode: true, taskPlaceholder: 'admin text' }))
            .toBe('runComposer.runningPlaceholder');
        expect(composerPlaceholder(t, { ...base, runTakesMessages: true, runAwaitingAnswer: true }))
            .toBe('com_linsight_answer_placeholder');
    });

    it('says a message continues the work after a stop, in either mode', () => {
        expect(composerPlaceholder(t, { ...base, runStopped: true })).toBe('runComposer.stoppedPlaceholder');
        expect(composerPlaceholder(t, { ...base, runStopped: true, taskMode: true, taskPlaceholder: 'admin text' }))
            .toBe('runComposer.stoppedPlaceholder');
    });

    it('keeps the earlier wording for the states that existed before', () => {
        expect(composerPlaceholder(t, { ...base, runAwaitingAnswer: true })).toBe('com_linsight_answer_placeholder');
        expect(composerPlaceholder(t, { ...base, taskMode: true })).toBe('com_linsight_input_placeholder');
        expect(composerPlaceholder(t, { ...base, taskMode: true, taskPlaceholder: 'admin text' })).toBe('admin text');
    });

    it('asks for the answer first when a question is pending', () => {
        expect(composerPlaceholder(t, { ...base, runAwaitingAnswer: true, runStopped: true }))
            .toBe('com_linsight_answer_placeholder');
    });
});

describe('useReturnedDraft', () => {
    const renderComposer = (cid: string, initial = '') =>
        renderHook(() => {
            const [text, setText] = useState(initial);
            useReturnedDraft(cid, setText);
            return { text, setText };
        });
    const giveBack = (messages: Array<[string, string]>, cid = 'c1') =>
        act(() => {
            const store = useRunStore.getState();
            store.applyUnreadMessages(cid, messages.map(([message_id, text]) => ({ message_id, text })));
            store.resolveReturnedMessages(cid, new Set(messages.map(([id]) => id)));
        });

    it('puts the returned text into an empty input box, in send order', () => {
        const { result } = renderComposer('c1');
        giveBack([['m1', 'first'], ['m2', 'second']]);
        expect(result.current.text).toBe('first\n\nsecond');
        expect(useRunStore.getState().conversations.c1.draftReturn).toBeNull();
    });

    it('puts it before what the user has typed since', () => {
        const { result } = renderComposer('c1', 'typed since');
        giveBack([['m1', 'first']]);
        expect(result.current.text).toBe('first\n\ntyped since');
    });

    it('takes each returned message once', () => {
        const { result } = renderComposer('c1');
        giveBack([['m1', 'first']]);
        giveBack([['m1', 'first']]);
        expect(result.current.text).toBe('first');
        act(() => result.current.setText(''));
        expect(result.current.text).toBe('');
    });

    it('ignores another conversation and a draft', () => {
        const other = renderComposer('other');
        const draft = renderComposer('');
        giveBack([['m1', 'first']]);
        expect(other.result.current.text).toBe('');
        expect(draft.result.current.text).toBe('');
        expect(useRunStore.getState().conversations.c1.draftReturn).toBe('first');
    });
});
