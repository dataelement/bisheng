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
        expect(screen.getByText('4/4')).toBeInTheDocument();
        expect(screen.queryByText('4/7')).not.toBeInTheDocument();
    });

    it('keeps every row when the user stopped the run', () => {
        // Gate-keeper: the stop path renders exactly as it did before this change.
        render(<TaskPanel tasks={[...FOUR_DONE, ...THREE_PRUNED]} completed terminated />);
        expect(screen.getByText('4/7')).toBeInTheDocument();
    });

    it('keeps not-started rows while the run is still going', () => {
        const running = [...FOUR_DONE, task('e', 'in_progress'), task('f', 'not_started')];
        render(<TaskPanel tasks={running} completed={false} />);
        expect(screen.getByText('4/6')).toBeInTheDocument();
    });

    it('renders nothing when every row was pruned', () => {
        const { container } = render(<TaskPanel tasks={THREE_PRUNED} completed />);
        expect(container).toBeEmptyDOMElement();
    });
});
