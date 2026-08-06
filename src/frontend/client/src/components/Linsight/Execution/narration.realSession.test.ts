/**
 * Narration regression, pinned to a REAL captured session.
 *
 * Fixture: `linsight_execute_task.history` of the "思源电气 PPT" run (108 frames,
 * 64 thinking segments), taken verbatim off a running deployment — only tool
 * `params`/`output` were dropped (grouping and narration never read them).
 *
 * It exists because the shipped rules reproduced, word for word, four asides that
 * read as broken Chinese in the UI:
 *
 *   node[0] "输出格式？"            a question the model posed to ITSELF
 *   node[3] "未来展望14."           two outline items welded by a lost line break
 *   node[5] "结尾页 - 感谢聆听"      a slide heading the model was drafting
 *
 * Two properties are locked here, and the second is the one unit tests kept missing:
 *
 *  1. the final aside of each group is a whole, self-contained sentence;
 *  2. EVERY streaming prefix is too. NarrationTicker (`NarrationTicker.tsx`) keeps
 *     the last non-empty result on screen to avoid flicker, so a bad line that
 *     passes the gates for one frame stays pinned even after better text arrives.
 *     Asserting only on the finished passage cannot see that — the old rules pinned
 *     14 slide headings in a row on node[5] before settling on the worst of them.
 */

import history from './__fixtures__/linsightSieyuanPptHistory.json';
import type { ExecStepEventData, MergedStep, TimelineNode } from './stepUtils';
import {
    buildTimelineGroups,
    extractNarration,
    mergeAdjacentThinking,
    mergeStepFrames,
    narrationFromSteps,
} from './stepUtils';

const nodes: TimelineNode[] = buildTimelineGroups(
    mergeAdjacentThinking(mergeStepFrames(history as ExecStepEventData[])),
);

function groupSteps(index: number): MergedStep[] {
    const node = nodes[index] as Extract<TimelineNode, { kind: 'deep_step_group' }>;
    expect(node.kind).toBe('deep_step_group');
    return node.steps;
}

/**
 * Shapes that mean "the model was drafting a deliverable", written independently of
 * the implementation so this stays a real check rather than a restatement of it.
 */
const DRAFTED_SHAPES: Array<[string, RegExp]> = [
    ['leading list marker', /^\s*(?:[-*•‣◦]|\d+[.)]|[（(]\d+[）)])\s/],
    ['self-posed question', /[?？]\s*$/],
    ['fused outline ordinal', /\S\d{1,3}[.)]\s*$/],
    ['dashed heading', /^[^。！？.!?]{1,20}\s[-–—]\s\S+$/],
];

function draftedShapeOf(line: string): string | null {
    for (const [label, re] of DRAFTED_SHAPES) {
        if (re.test(line)) return label;
    }
    return null;
}

/** The sequence NarrationTicker would pin, replaying the passage token by token. */
function pinnedWhileStreaming(text: string): string[] {
    const pinned: string[] = [];
    let last = '';
    for (let n = 1; n <= text.length; n++) {
        const value = extractNarration(text.slice(0, n));
        // '' is ignored by the ticker (it keeps showing `last`) — mirror that here.
        if (value && value !== last) {
            pinned.push(value);
            last = value;
        }
    }
    return pinned;
}

function lastThinkingText(steps: MergedStep[]): string {
    const thinking = steps.filter((s) => s.stepType === 'thinking');
    expect(thinking.length).toBeGreaterThan(0);
    return thinking[thinking.length - 1].output || '';
}

describe('narration on a real captured session (思源电气 PPT)', () => {
    it('reads the fixture as the same timeline the UI rendered', () => {
        // Guards the fixture itself: if grouping changes shape, the assertions below
        // would silently start describing different groups.
        expect(nodes).toHaveLength(7);
        expect(nodes[1].kind).toBe('intent'); // the answered clarify, inline
    });

    it.each([
        [0, '输出格式？'],
        [3, '未来展望14.'],
        [5, '结尾页 - 感谢聆听'],
    ])('group %i no longer settles on the broken aside %p', (index, broken) => {
        const narration = narrationFromSteps(groupSteps(index as number), false);
        expect(narration).not.toBe(broken);
        expect(draftedShapeOf(narration)).toBeNull();
        expect(narration.length).toBeGreaterThan(0);
    });

    it('keeps the already-good aside on the group that had one', () => {
        // node[4] was never broken — proof the new rules did not just blank things out.
        expect(narrationFromSteps(groupSteps(4), false)).toBe('现在开始写JS脚本。');
    });

    it.each([0, 3, 5])('pins nothing drafted while group %i streams in', (index) => {
        const offenders = pinnedWhileStreaming(lastThinkingText(groupSteps(index)))
            .map((line) => ({ line, shape: draftedShapeOf(line) }))
            .filter((x) => x.shape);
        expect(offenders).toEqual([]);
    });
});
