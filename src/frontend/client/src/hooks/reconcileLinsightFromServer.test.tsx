/**
 * Regression cover for the terminal-event race that strands a finished task-mode
 * run on a spinning panel.
 *
 * Field case (2026-08-13): a 46-minute run pushed FINAL_RESULT at 20:35:21.034
 * and the client's replacement socket connected at 20:35:22.116 — 1.08s late.
 * The backend hands terminal events out with a destructive BLPOP, so the dying
 * socket's server coroutine took the event with it; the reconnect then blocked
 * on an empty queue and the panel spun for hours at "4/7" over a run whose DB
 * row had said `completed` the whole time.
 *
 * reconcileLinsightFromServer closes that window on every WS open — but ONLY in
 * one direction: it must never overwrite a live run with an async snapshot that
 * raced past newer stream events.
 */
import { renderHook, act } from '@testing-library/react';
import React from 'react';
// Test harness for the EXISTING recoil-backed useLinsightManager; ledger #5 bans
// new atoms/selectors, not the provider needed to render the store under test.
// eslint-disable-next-line no-restricted-imports
import { RecoilRoot } from 'recoil';
import { getLinsightSessionVersionList, getLinsightTaskList } from '~/api/linsight';
import { SopStatus, type LinsightInfo } from '~/store/linsight';
import { useLinsightManager } from './useLinsightManager';

// sse.js ships ESM that jest does not transform; useLinsightManager only needs
// the symbol at import time (the submit pipeline is not under test here).
jest.mock('sse.js', () => ({ SSE: class {} }));
// The ~/Providers barrel drags the whole UI layer in (and with it more
// untransformed ESM). useLinsightManager only reaches for useToastContext, and
// only from the submit pipeline — stub the barrel instead of the world.
jest.mock('~/Providers', () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock('~/api/linsight', () => ({
    getLinsightSessionVersionList: jest.fn(),
    getLinsightTaskList: jest.fn(),
    continueLinsight: jest.fn(),
    startLinsight: jest.fn(),
}));

const mockVersionList = getLinsightSessionVersionList as jest.Mock;
const mockTaskList = getLinsightTaskList as jest.Mock;

const VERSION_ID = '012d4c4566274bb3b0140c2850301f9c';
const SESSION_ID = '94f631c8a6184941877d7464306fc265';

const wrapper = ({ children }: { children: React.ReactNode }) =>
    React.createElement(RecoilRoot, null, children);

/** Store state as the live WS pump left it: mid-run, frozen at 4 of 7 tasks. */
const liveSnapshot = {
    session_id: SESSION_ID,
    status: SopStatus.Running,
    tasks: [
        { id: 't1', name: 'D1', status: 'success', history: [], children: [] },
        { id: 't2', name: 'D4', status: 'in_progress', history: [], children: [] },
    ],
    output_result: null,
    file_list: [],
    queueCount: 0,
    // Deliberately partial: this is the slice the WS pump had actually filled
    // in, not a complete LinsightInfo. `as unknown as` keeps the fixture honest
    // (no invented fields) without reaching for `any`.
} as unknown as Omit<LinsightInfo, 'id'>;

/** What the DB actually held: everything finished. */
const serverTasks = [
    { id: 't1', task_data: { name: 'D1' }, status: 'success', history: [] },
    { id: 't2', task_data: { name: 'D4' }, status: 'success', history: [] },
];

const renderManager = () => {
    const { result } = renderHook(() => useLinsightManager(), { wrapper });
    act(() => {
        result.current.createLinsight(VERSION_ID, liveSnapshot);
    });
    return result;
};

describe('reconcileLinsightFromServer', () => {
    beforeEach(() => jest.clearAllMocks());

    it('adopts a completed run the stream never delivered', async () => {
        mockVersionList.mockResolvedValue([
            {
                id: VERSION_ID,
                status: 'completed',
                execute_feedback: null,
                message_id: 4242,
                liked: 1,
                output_result: {
                    // Fixture data: a model answer in Chinese, not UI copy to localize.
                    // eslint-disable-next-line no-restricted-syntax
                    answer: '所有5项交付物已全部生成完毕。',
                    final_files: [{ file_name: 'D1_Tanzania_Parameter_Viewer.html' }],
                },
            },
        ]);
        mockTaskList.mockResolvedValue(serverTasks);

        const result = renderManager();
        let adopted: boolean | undefined;
        await act(async () => {
            adopted = await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        expect(adopted).toBe(true);
        const info = result.current.getLinsight(VERSION_ID)!;
        expect(info.status).toBe(SopStatus.completed);
        // eslint-disable-next-line no-restricted-syntax -- asserts on the fixture above.
        expect(info.output_result.answer).toContain('交付物');
        expect(info.file_list).toHaveLength(1);
        // The frozen progress count converges too — the whole point of pulling
        // the task list rather than just flipping the session status.
        expect(info.tasks.map((t) => t.status)).toEqual(['success', 'success']);
        // Like/dislike must target the persisted row, mirroring final_result.
        expect(info.message_id).toBe(4242);
        expect(info.liked).toBe(1);
    });

    it('keeps tasks that follow a model-pruned todo intact', async () => {
        // `terminated` no longer means only "the user hit stop": _diff_todos marks a
        // todo terminated when the MODEL drops it from its own plan. buildTaskTree
        // used to treat the first terminated row as a cutoff and rewrite everything
        // after it to `not_started`, so session 8a570723 on 114 — 8 successful tasks
        // in the DB, one pruned todo sitting fourth — rendered "任务已完成 3/18" with
        // unfilled rings, and those tasks' steps dropped out of the timeline as well
        // (isTaskStarted('not_started') is false).
        mockVersionList.mockResolvedValue([
            {
                id: VERSION_ID,
                status: 'completed',
                execute_feedback: null,
                output_result: { answer: '', final_files: [] },
            },
        ]);
        mockTaskList.mockResolvedValue([
            { id: 'p1', task_data: { name: 'Build parameter table' }, status: 'success', history: [] },
            { id: 'p2', task_data: { name: 'Pruned extraction todo' }, status: 'terminated', history: [] },
            { id: 'p3', task_data: { name: 'D3' }, status: 'success', history: [] },
            { id: 'p4', task_data: { name: 'D5' }, status: 'success', history: [] },
        ]);

        const result = renderManager();
        await act(async () => {
            await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        const info = result.current.getLinsight(VERSION_ID)!;
        expect(info.tasks.map((t) => t.status)).toEqual(['success', 'terminated', 'success', 'success']);
    });

    it('leaves a still-running session untouched and skips the task fetch', async () => {
        mockVersionList.mockResolvedValue([
            { id: VERSION_ID, status: 'in_progress', output_result: null },
        ]);

        const result = renderManager();
        let adopted: boolean | undefined;
        await act(async () => {
            adopted = await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        expect(adopted).toBe(false);
        // Overwriting here would clobber WS events that landed while the
        // snapshot was in flight — the reason this is one-way.
        expect(result.current.getLinsight(VERSION_ID)!.status).toBe(SopStatus.Running);
        expect(result.current.getLinsight(VERSION_ID)!.tasks).toHaveLength(2);
        expect(mockTaskList).not.toHaveBeenCalled();
    });

    // A parked run is waiting on the user, NOT finished: adopting it would kill
    // the ClarifyCard and drop the answer box the run is blocked on.
    it('treats waiting_for_user_input (parked HITL) as non-terminal', async () => {
        mockVersionList.mockResolvedValue([
            { id: VERSION_ID, status: 'waiting_for_user_input', output_result: null },
        ]);

        const result = renderManager();
        let adopted: boolean | undefined;
        await act(async () => {
            adopted = await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        expect(adopted).toBe(false);
        expect(result.current.getLinsight(VERSION_ID)!.status).toBe(SopStatus.Running);
        expect(mockTaskList).not.toHaveBeenCalled();
    });

    // `not_started` means queued (the worker has not dequeued it yet), so it is
    // not terminal either — see mapSessionVersionStatus.
    it('treats not_started (queued) as non-terminal', async () => {
        mockVersionList.mockResolvedValue([
            { id: VERSION_ID, status: 'not_started', output_result: null },
        ]);

        const result = renderManager();
        let adopted: boolean | undefined;
        await act(async () => {
            adopted = await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        expect(adopted).toBe(false);
        expect(mockTaskList).not.toHaveBeenCalled();
    });

    it('adopts a terminated run as stopped', async () => {
        mockVersionList.mockResolvedValue([
            { id: VERSION_ID, status: 'terminated', output_result: null },
        ]);
        mockTaskList.mockResolvedValue(serverTasks);

        const result = renderManager();
        await act(async () => {
            await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        expect(result.current.getLinsight(VERSION_ID)!.status).toBe(SopStatus.Stoped);
        // getLinsightTaskList needs the RAW backend status to rewrite lingering
        // in_progress rows, so the server item — not the mapped store value —
        // must be what gets handed to it.
        expect(mockTaskList).toHaveBeenCalledWith(
            VERSION_ID,
            expect.objectContaining({ status: 'terminated' }),
            '',
        );
    });

    it('surfaces a failed run with its error message', async () => {
        mockVersionList.mockResolvedValue([
            {
                id: VERSION_ID,
                status: 'failed',
                output_result: { error_message: 'model quota exhausted' },
            },
        ]);
        mockTaskList.mockResolvedValue(serverTasks);

        const result = renderManager();
        await act(async () => {
            await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        const info = result.current.getLinsight(VERSION_ID)!;
        expect(info.status).toBe(SopStatus.Stoped);
        expect(info.taskError).toBe('model quota exhausted');
    });

    it('no-ops when the version is unknown to the store (nothing to query by)', async () => {
        const result = renderManager();
        let adopted: boolean | undefined;
        await act(async () => {
            adopted = await result.current.reconcileLinsightFromServer('some-other-version');
        });

        expect(adopted).toBe(false);
        expect(mockVersionList).not.toHaveBeenCalled();
    });

    it('no-ops when the server does not list this version', async () => {
        mockVersionList.mockResolvedValue([{ id: 'a-different-version', status: 'completed' }]);

        const result = renderManager();
        let adopted: boolean | undefined;
        await act(async () => {
            adopted = await result.current.reconcileLinsightFromServer(VERSION_ID);
        });

        expect(adopted).toBe(false);
        expect(result.current.getLinsight(VERSION_ID)!.status).toBe(SopStatus.Running);
        expect(mockTaskList).not.toHaveBeenCalled();
    });
});
