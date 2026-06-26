/**
 * DeepStepGroup — regression guard for the anti-flicker fix + the quiet-open fold.
 *
 * Root cause the anti-flicker fix locks down: the group's live-vs-done UI used to be
 * driven by `group.running` ("any step mid-flight"), which toggles true↔false many
 * times within ONE live episode — thinking frames ship as `status:'end'` (never
 * running) and a tool step is running only between its start/end frames. Binding the
 * 正在/已 label (and, before b1ff8967a, the fold) to it made the group flicker on
 * every tool call ("内容上下反复跳跃").
 *
 * Current contract these tests assert:
 *  - the 正在/已 LABEL follows the stable `active` prop (the live tail episode, owned
 *    by ExecutionTimeline), NOT `group.running`;
 *  - the FOLD defaults COLLAPSED for every group — even the live tail — so task mode
 *    opens quiet (b1ff8967a); it is bound to neither `active` nor `group.running`.
 */
import { render } from '@testing-library/react';
import { RecoilRoot } from 'recoil';
import { DeepStepGroup } from './DeepStepGroup';
import type { DeepStepGroup as DeepStepGroupData, MergedStep } from './stepUtils';

// useLocalize → identity so the rendered label IS the i18n key (assertable).
jest.mock('~/hooks', () => ({
    __esModule: true,
    useLocalize: () => (key: string) => key,
}));

// jsdom has no IntersectionObserver; the sticky-header pin detection news one up
// on mount. Stub it as an inert no-op so the group renders.
beforeAll(() => {
    class MockIO {
        observe() {}
        unobserve() {}
        disconnect() {}
        takeRecords() {
            return [];
        }
    }
    (window as any).IntersectionObserver = MockIO;
    (global as any).IntersectionObserver = MockIO;
});

const RUNNING_LABEL = 'com_linsight_deep_thinking_running';
const DONE_LABEL = 'com_linsight_deep_thinking_done';

/** One thinking step. Thinking is the minimal render tree (no tool/knowledge child
 *  rows, so no extra hook deps) and always lands as a `status:'end'` frame, i.e.
 *  running=false — exactly the case the old code mis-collapsed. */
function thinkingStep(callId: string, output: string): MergedStep {
    return {
        callId,
        taskId: 't',
        name: 'thinking',
        stepType: 'thinking',
        running: false,
        callReason: '',
        params: null,
        output,
        namespace: null,
        extraInfo: {},
        // far-past second-level stamps so the live ticker measures elapsedMs > 0
        // (the label keeps its 用时/已用 clause instead of the 0s compact form).
        startedAt: 1000,
        endedAt: 1200,
        raw: {} as any,
    };
}

function makeGroup(running: boolean, steps: MergedStep[]): DeepStepGroupData {
    return { kind: 'deep_step_group', steps, startedAt: 1000, endedAt: 1200, running };
}

function renderGroup(group: DeepStepGroupData, active: boolean) {
    return render(
        <RecoilRoot>
            <DeepStepGroup group={group} active={active} />
        </RecoilRoot>,
    );
}

/** The group's own fold container is the only element carrying an inline
 *  grid-template-rows (thinking-only group renders no nested collapsibles). */
function foldRows(container: HTMLElement): string {
    const grid = container.querySelector('[style*="grid-template-rows"]') as HTMLElement;
    return grid.style.gridTemplateRows;
}

describe('DeepStepGroup — label follows `active`; fold opens quiet, bound to neither', () => {
    it('active=true shows the running label, yet opens collapsed (quiet) even as the live tail', () => {
        const { container, getByText } = renderGroup(
            makeGroup(false, [thinkingStep('c1', 'reasoning…')]),
            true,
        );
        getByText(RUNNING_LABEL); // label follows active, not the (false) group.running
        // Every group — even the live tail — defaults collapsed so task mode opens
        // quiet (b1ff8967a); the collapsed header still streams via the NarrationTicker.
        expect(foldRows(container)).toBe('0fr');
    });

    it('active=false collapses and shows the done label even while group.running=true (the regression guard)', () => {
        // group.running=true would, under the old code, force-expand + "正在" —
        // the exact per-tool-call flicker we removed.
        const { container, getByText, queryByText } = renderGroup(
            makeGroup(true, [thinkingStep('c1', 'reasoning…')]),
            false,
        );
        getByText(DONE_LABEL);
        expect(queryByText(RUNNING_LABEL)).toBeNull();
        expect(foldRows(container)).toBe('0fr'); // collapsed
    });

    it('toggling group.running while active stays true changes neither the label nor the (collapsed) fold (anti-flicker)', () => {
        const steps = [thinkingStep('c1', 'reasoning…')];
        const { container, rerender, getByText } = render(
            <RecoilRoot>
                <DeepStepGroup group={makeGroup(false, steps)} active={true} />
            </RecoilRoot>,
        );
        getByText(RUNNING_LABEL);
        expect(foldRows(container)).toBe('0fr');

        // a tool call starts → group.running flips true … (active unchanged)
        rerender(
            <RecoilRoot>
                <DeepStepGroup group={makeGroup(true, steps)} active={true} />
            </RecoilRoot>,
        );
        getByText(RUNNING_LABEL);
        expect(foldRows(container)).toBe('0fr');

        // … and ends → group.running flips back to false (active still unchanged)
        rerender(
            <RecoilRoot>
                <DeepStepGroup group={makeGroup(false, steps)} active={true} />
            </RecoilRoot>,
        );
        getByText(RUNNING_LABEL);
        expect(foldRows(container)).toBe('0fr'); // fold never flips with group.running
    });
});
