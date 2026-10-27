/**
 * A finished run must not report a fake ratio.
 *
 * Session `aa352cb4…` (180 POC, 2026-08-08) rendered "任务已完成 4/7" on a run that
 * had succeeded: the backend never converged `linsight_execute_task`, so three rows
 * the model had pruned from its plan stayed in the list. The backend now sweeps them
 * to `terminated`, but `terminated` is neither done nor running, so it used to render
 * as a grey ring indistinguishable from `not_started` and still counted toward the
 * denominator. This pins the split: hide them on a normally-completed run, keep every
 * row when the user stopped the run.
 *
 * The second block pins the wrap-up window (customer session 436f0765, 2026-09-10):
 * a run whose todos are all ticked off but whose session is still Running must not
 * report "任务已完成" — the stream above it is still spinning "正在执行任务", and
 * that row reads the session status, which is the only authority on whether the run
 * is over.
 */
import { render, screen } from '@testing-library/react';
import { TaskPanel } from './TaskPanel';

jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy(
        {},
        {
            get: () => () => null,
        },
    ),
}));

const task = (id: string, status: string) => ({ id, name: id, status }) as never;

const FOUR_DONE = [
    task('a', 'success'),
    task('b', 'success'),
    task('c', 'success'),
    task('d', 'success'),
];
const THREE_PRUNED = [task('e', 'terminated'), task('f', 'terminated'), task('g', 'terminated')];

describe('TaskPanel progress ratio', () => {
    it('hides pruned rows on a normally completed run', () => {
        render(<TaskPanel tasks={[...FOUR_DONE, ...THREE_PRUNED]} completed />);
        expect(screen.getByText('4/4')).toBeTruthy();
        expect(screen.queryByText('4/7')).toBeNull();
    });

    it('keeps every row when the user stopped the run', () => {
        // Gate-keeper: the stop path renders exactly as it did before this change.
        render(<TaskPanel tasks={[...FOUR_DONE, ...THREE_PRUNED]} completed terminated />);
        expect(screen.getByText('4/7')).toBeTruthy();
    });

    it('keeps not-started rows while the run is still going', () => {
        const running = [...FOUR_DONE, task('e', 'in_progress'), task('f', 'not_started')];
        render(<TaskPanel tasks={running} completed={false} />);
        expect(screen.getByText('4/6')).toBeTruthy();
    });

    it('renders nothing when every row was pruned', () => {
        const { container } = render(<TaskPanel tasks={THREE_PRUNED} completed />);
        expect(container.firstChild).toBeNull();
    });
});

describe('TaskPanel header state', () => {
    it('does not declare the run finished while the session is still running', () => {
        // Wrap-up window: the model ticked off its last todo, the backend is still
        // synthesizing the deliverable. Both signals derive from the same data, so
        // this is not a race — the panel used to contradict the stream every time.
        render(<TaskPanel tasks={FOUR_DONE} completed={false} running />);
        expect(screen.getByText('com_linsight_task_panel_wrapping_up')).toBeTruthy();
        expect(screen.queryByText('com_linsight_task_panel_done')).toBeNull();
        expect(screen.getByText('4/4')).toBeTruthy();
    });

    it('declares the run finished once the session status says so', () => {
        render(<TaskPanel tasks={FOUR_DONE} completed running={false} />);
        expect(screen.getByText('com_linsight_task_panel_done')).toBeTruthy();
        expect(screen.queryByText('com_linsight_task_panel_wrapping_up')).toBeNull();
    });

    it('keeps the plain task header while a task is still running', () => {
        const inFlight = [...FOUR_DONE, task('e', 'in_progress')];
        render(<TaskPanel tasks={inFlight} completed={false} running />);
        expect(screen.getByText('com_linsight_task_panel')).toBeTruthy();
    });

    it('still flags a manually stopped run', () => {
        // Gate-keeper: the stop path outranks the wrap-up window.
        render(<TaskPanel tasks={FOUR_DONE} completed={false} running terminated />);
        expect(screen.getByText('com_linsight_task_terminated')).toBeTruthy();
    });
});
