/**
 * F004 (T049): the pinned plan panel reads `runStore` on the unified runtime
 * and the linsight Recoil store everywhere else.
 */
import { act, render, screen } from '@testing-library/react';
import { useRunStore, type RunEvent, type RunPlanItem } from '~/store/runStore';
import { PinnedTaskPanel, planItemsToTasks } from './PinnedTaskPanel';

let mockUnified: boolean | undefined = true;
let mockLinsight: unknown = null;

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
}));
jest.mock('~/hooks/queries/data-provider', () => ({
    useGetBsConfig: () => ({ data: { unified_runtime_enabled: mockUnified } }),
}));
jest.mock('~/hooks/useLinsightManager', () => ({
    useLinsightManager: () => ({ getLinsight: () => mockLinsight }),
}));
jest.mock('~/store/linsight', () => ({
    SopStatus: { completed: 'completed', FeedbackCompleted: 'feedback_completed', Stoped: 'stoped', Running: 'running' },
}));
jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy({}, { get: () => () => null }),
}));

const CID = 'conv-1';
const RUN = 'run-1';

const item = (id: string, status: RunPlanItem['status'], extra: Partial<RunPlanItem> = {}): RunPlanItem => ({
    id,
    content: `step ${id}`,
    status,
    ...extra,
});

function apply(event: Omit<RunEvent, 'run_id'> & { run_id?: string }, cid = CID) {
    act(() => {
        useRunStore.getState().applyEvent(cid, { run_id: RUN, ...event } as RunEvent);
    });
}

function plan(items: RunPlanItem[]) {
    apply({ type: 'plan', data: { items } });
}

beforeEach(() => {
    mockUnified = true;
    mockLinsight = null;
    act(() => useRunStore.setState({ conversations: {} }));
});

describe('planItemsToTasks', () => {
    it('maps statuses and carries the previous wording', () => {
        const tasks = planItemsToTasks(
            [
                item('1', 'completed'),
                item('2', 'in_progress', { previous_content: 'old 2' }),
                item('3', 'pending'),
                item('4', 'cancelled'),
            ],
            'running',
        );
        expect(tasks.map((t) => t.status)).toEqual(['success', 'in_progress', 'not_started', 'cancelled']);
        expect(tasks[1].previousName).toBe('old 2');
        expect(tasks[0].previousName).toBe('');
        expect(tasks.map((t) => t.id)).toEqual(['1', '2', '3', '4']);
    });

    it.each(['stopped', 'failed', 'finished'] as const)('leaves no row in progress once the run is %s', (status) => {
        const tasks = planItemsToTasks([item('1', 'completed'), item('2', 'in_progress')], status);
        expect(tasks.map((t) => t.status)).toEqual(['success', 'not_started']);
    });
});

describe('PinnedTaskPanel on the unified runtime', () => {
    it('renders nothing while the run has no plan', () => {
        apply({ type: 'run_started', data: {} });
        const { container } = render(<PinnedTaskPanel conversationId={CID} />);
        expect(container.firstChild).toBeNull();
    });

    it('shows done / total from the run store and follows plan events (AC-08)', () => {
        apply({ type: 'run_started', data: {} });
        plan([item('1', 'completed'), item('2', 'in_progress'), item('3', 'pending')]);
        render(<PinnedTaskPanel conversationId={CID} />);
        expect(screen.getByText('1/3')).toBeTruthy();

        plan([item('1', 'completed'), item('2', 'completed'), item('3', 'in_progress')]);
        expect(screen.getByText('2/3')).toBeTruthy();
    });

    it('shows a rewritten row with the old wording struck through, other rows unchanged (AC-09, AC-10)', () => {
        apply({ type: 'run_started', data: {} });
        plan([
            item('1', 'completed'),
            item('2', 'in_progress'),
            item('3', 'pending', { content: 'make a deck', previous_content: 'write a report' }),
        ]);
        const { container } = render(<PinnedTaskPanel conversationId={CID} />);
        const struck = container.querySelectorAll('del');
        expect(struck).toHaveLength(1);
        expect(struck[0].textContent).toBe('write a report');
        expect(screen.getByText('step 1')).toBeTruthy();
        expect(screen.getByText('1/3')).toBeTruthy();
        const rows = Array.from(container.querySelectorAll('li')).map((li) => li.textContent);
        expect(rows).toEqual(['step 1', 'step 2', 'write a reportmake a deck']);
    });

    it('labels a cancelled row (AC-11)', () => {
        apply({ type: 'run_started', data: {} });
        plan([item('1', 'completed'), item('2', 'cancelled'), item('3', 'in_progress')]);
        render(<PinnedTaskPanel conversationId={CID} />);
        expect(screen.getAllByText('runPlan.cancelled')).toHaveLength(1);
        expect(screen.getByText('1/2')).toBeTruthy();
    });

    it('reads "stopped" after run_stopped and keeps the finished rows', () => {
        apply({ type: 'run_started', data: {} });
        plan([item('1', 'completed'), item('2', 'in_progress')]);
        render(<PinnedTaskPanel conversationId={CID} />);
        apply({ type: 'run_stopped', data: {} });
        expect(screen.getByText('runPlan.stopped')).toBeTruthy();
        expect(screen.getByText('1/2')).toBeTruthy();
    });

    it('shows the kept-work note only after a stop', () => {
        apply({ type: 'run_started', data: {} });
        plan([item('1', 'completed'), item('2', 'in_progress')]);
        render(<PinnedTaskPanel conversationId={CID} />);
        expect(screen.queryByText('runPlan.stoppedNote')).toBeNull();
        apply({ type: 'run_stopped', data: {} });
        // Visible without expanding the panel.
        expect(screen.getByText('runPlan.stoppedNote')).toBeTruthy();
    });

    it('says the run continues after the answer while a question is pending', () => {
        apply({ type: 'run_started', data: {} });
        plan([item('1', 'completed'), item('2', 'in_progress')]);
        render(<PinnedTaskPanel conversationId={CID} />);
        expect(screen.queryByText('runPlan.awaitingAnswer')).toBeNull();
        // Collapsed header names the row in progress.
        expect(screen.getAllByText('step 2')).toHaveLength(2);
        apply({ type: 'ask_user', data: { call_id: 'q1', questions: [{ question: 'Which one?' }] } });
        expect(screen.getByText('runPlan.awaitingAnswer')).toBeTruthy();
        // Nothing is executing: the header no longer names a running row.
        expect(screen.getAllByText('step 2')).toHaveLength(1);
        expect(screen.getByText('1/2')).toBeTruthy();
        apply({ type: 'ask_user_answered', data: { call_id: 'q1' } });
        expect(screen.queryByText('runPlan.awaitingAnswer')).toBeNull();
        expect(screen.getAllByText('step 2')).toHaveLength(2);
    });

    it('is filled by a resync snapshot, as after a page refresh', () => {
        apply({
            type: 'resync',
            data: {
                text: '',
                thinking: '',
                files: [],
                plan: [item('1', 'completed'), item('2', 'in_progress', { previous_content: 'old 2' })],
            },
        });
        const { container } = render(<PinnedTaskPanel conversationId={CID} />);
        expect(screen.getByText('1/2')).toBeTruthy();
        expect(container.querySelector('del')?.textContent).toBe('old 2');
    });

    it('ignores the plan of another conversation', () => {
        apply({ type: 'run_started', data: {} }, 'other');
        act(() => {
            useRunStore
                .getState()
                .applyEvent('other', { type: 'plan', data: { items: [item('1', 'pending')] }, run_id: RUN });
        });
        const { container } = render(<PinnedTaskPanel conversationId={CID} />);
        expect(container.firstChild).toBeNull();
    });

    it('falls back to the legacy source when the store holds no plan', () => {
        mockLinsight = { status: 'running', tasks: [{ id: 't1', name: 'legacy row', status: 'success' }] };
        render(<PinnedTaskPanel versionId="v1" conversationId={CID} />);
        expect(screen.getByText('legacy row')).toBeTruthy();
    });
});

describe('PinnedTaskPanel with the switch off', () => {
    it.each([false, undefined])('reads only the legacy source when the flag is %s', (flag) => {
        mockUnified = flag;
        apply({ type: 'run_started', data: {} });
        plan([item('1', 'completed'), item('2', 'in_progress')]);
        mockLinsight = { status: 'running', tasks: [{ id: 't1', name: 'legacy row', status: 'in_progress' }] };
        render(<PinnedTaskPanel versionId="v1" conversationId={CID} />);
        // Header (running row inline) + list row.
        expect(screen.getAllByText('legacy row').length).toBeGreaterThan(0);
        expect(screen.queryByText('step 1')).toBeNull();
        expect(screen.getByText('0/1')).toBeTruthy();
    });

    it('renders nothing without a task turn', () => {
        mockUnified = false;
        apply({ type: 'run_started', data: {} });
        plan([item('1', 'completed')]);
        const { container } = render(<PinnedTaskPanel conversationId={CID} />);
        expect(container.firstChild).toBeNull();
    });
});
