/**
 * timelineMemo — guards the React.memo comparators that keep the task-mode
 * execution timeline from re-rendering frozen episodes on every WS frame (the fix
 * for the "用时 N 秒" counter advancing unevenly / skipping seconds under a thinking
 * token-delta storm). The critical contract: the WS pump rebuilds the whole node
 * tree with FRESH objects each frame, so an unchanged (frozen) episode must compare
 * EQUAL across rebuilds (skip re-render), while any real change in the active tail
 * must compare UNEQUAL (re-render).
 */
import { deepStepGroupPropsEqual } from './DeepStepGroup';
import { toolRowLitePropsEqual } from './ToolRowLite';
import type { DeepStepGroup as DeepStepGroupData, MergedStep } from './stepUtils';

// useLocalize is only called inside the component, but importing DeepStepGroup
// pulls the module graph in — mirror the sibling test's hook stub so it resolves.
jest.mock('~/hooks', () => ({
    __esModule: true,
    useLocalize: () => (key: string) => key,
}));

const SHARED_PARAMS = { q: 'a' }; // a stable raw-frame reference (what mergeStepFrames reuses)

function step(overrides: Partial<MergedStep> = {}): MergedStep {
    return {
        callId: 'c1',
        taskId: 't',
        name: 'thinking',
        stepType: 'thinking',
        running: false,
        callReason: '',
        params: null,
        output: 'abc',
        namespace: null,
        extraInfo: {},
        startedAt: 1000,
        endedAt: 1200,
        raw: {} as any,
        ...overrides,
    };
}

/** Clone a step into a NEW object with identical field values — the rebuild case. */
function rebuilt(s: MergedStep): MergedStep {
    return { ...s, extraInfo: {} }; // fresh extraInfo, as mergeStepFrames spreads one each pass
}

function group(steps: MergedStep[], overrides: Partial<DeepStepGroupData> = {}): DeepStepGroupData {
    return { kind: 'deep_step_group', steps, startedAt: 1000, endedAt: 1200, running: false, ...overrides };
}

describe('deepStepGroupPropsEqual', () => {
    it('treats a rebuilt-but-unchanged frozen episode as EQUAL (skip re-render)', () => {
        const s = step({ params: SHARED_PARAMS });
        const a = { group: group([s]), active: false, compact: false };
        const b = { group: group([rebuilt(s)]), active: false, compact: false };
        expect(deepStepGroupPropsEqual(a, b)).toBe(true);
    });

    it('re-renders when `active` flips (live tail ⇄ done)', () => {
        const s = step();
        expect(
            deepStepGroupPropsEqual(
                { group: group([s]), active: true, compact: false },
                { group: group([rebuilt(s)]), active: false, compact: false },
            ),
        ).toBe(false);
    });

    it('re-renders when a streaming step appends output (length grows)', () => {
        const s = step({ output: 'abc' });
        const grown = step({ output: 'abcdef' });
        expect(
            deepStepGroupPropsEqual(
                { group: group([s]), active: true, compact: false },
                { group: group([grown]), active: true, compact: false },
            ),
        ).toBe(false);
    });

    it('re-renders when a new step is appended to the episode', () => {
        const s = step({ callId: 'c1' });
        expect(
            deepStepGroupPropsEqual(
                { group: group([s]), active: true, compact: false },
                { group: group([rebuilt(s), step({ callId: 'c2', name: 'web_search', stepType: 'tool' })]), active: true, compact: false },
            ),
        ).toBe(false);
    });

    it('re-renders when a MIDDLE step closes (running true→false) — the subtle case', () => {
        // c2 is not the last step; a last-step-only signature would miss its close.
        const mk = (c2Running: boolean) => [
            step({ callId: 'c1', name: 'thinking' }),
            step({ callId: 'c2', name: 'web_search', stepType: 'tool', running: c2Running }),
            step({ callId: 'c3', name: 'thinking' }),
        ];
        expect(
            deepStepGroupPropsEqual(
                { group: group(mk(true)), active: true, compact: false },
                { group: group(mk(false)), active: true, compact: false },
            ),
        ).toBe(false);
    });

    it('re-renders when the group clock end stamp changes', () => {
        const s = step();
        expect(
            deepStepGroupPropsEqual(
                { group: group([s], { endedAt: 1200 }), active: true, compact: false },
                { group: group([rebuilt(s)], { endedAt: 1300 }), active: true, compact: false },
            ),
        ).toBe(false);
    });

    it('re-renders when a subagent segment goal changes; equal when same', () => {
        const s = step();
        const base = { group: group([s]), active: false, compact: false, subagent: { goal: 'research X', idx: 1 } };
        expect(
            deepStepGroupPropsEqual(base, {
                group: group([rebuilt(s)]),
                active: false,
                compact: false,
                subagent: { goal: 'research Y', idx: 1 },
            }),
        ).toBe(false);
        expect(
            deepStepGroupPropsEqual(base, {
                group: group([rebuilt(s)]),
                active: false,
                compact: false,
                subagent: { goal: 'research X', idx: 1 },
            }),
        ).toBe(true);
    });
});

describe('toolRowLitePropsEqual', () => {
    it('treats a rebuilt-but-unchanged tool row as EQUAL', () => {
        const s = step({ name: 'web_search', stepType: 'tool', params: SHARED_PARAMS, output: 'res' });
        expect(toolRowLitePropsEqual({ step: s }, { step: rebuilt(s) })).toBe(true);
    });

    it('re-renders when the tool step closes (running flip)', () => {
        const running = step({ name: 'web_search', stepType: 'tool', running: true });
        const done = step({ name: 'web_search', stepType: 'tool', running: false });
        expect(toolRowLitePropsEqual({ step: running }, { step: done })).toBe(false);
    });

    it('re-renders when output streams in (length grows)', () => {
        const a = step({ name: 'web_search', stepType: 'tool', output: '' });
        const b = step({ name: 'web_search', stepType: 'tool', output: 'hit list' });
        expect(toolRowLitePropsEqual({ step: a }, { step: b })).toBe(false);
    });

    it('re-renders when params first arrive (reference changes)', () => {
        const a = step({ name: 'web_search', stepType: 'tool', params: null });
        const b = step({ name: 'web_search', stepType: 'tool', params: SHARED_PARAMS });
        expect(toolRowLitePropsEqual({ step: a }, { step: b })).toBe(false);
    });
});
