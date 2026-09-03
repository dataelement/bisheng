/**
 * GroupHeaderLabel — the header text for a DeepStepGroup.
 *
 * **No duration (2026-08-13).** This used to end in "（用时 N 秒）", driven by a
 * 100ms ticker. It was removed on purpose, and the reasoning is worth keeping:
 *
 * A live counter is a promise that the number matters. For agent reasoning it
 * does not — nobody decides anything on "1416". What it does do is measure how
 * long you have been waiting, with no denominator to reason against, at a
 * precision (seconds) that implies the operation should have been quick. On a
 * 20-minute run the header read "读取 6 个文件 · 执行 1 步操作（用时 1416 秒）"
 * and the product looked broken rather than busy. Liveness is carried by the
 * narration line and the running glyph instead, which say what is happening
 * rather than how long it has hurt.
 *
 * Dropping it also removed the component's original reason to exist: it was split
 * out of DeepStepGroup so a 100ms setInterval would re-render one line instead of
 * the whole group (thinking passages + every tool row) ten times a second. That
 * timer is gone, so the surface displaying "how slow this is" is no longer itself
 * a source of slowness. The split is kept because the branch logic below is worth
 * isolating and testing on its own.
 */
import { useLocalize } from '~/hooks';
import { firstLine } from './stepUtils';

/**
 * Subagent header budget: the delegation goal is the `task` tool's `description`
 * arg (a long multi-sentence instruction). The header renders only its first
 * sentence/clause (firstLine), widened to ~one line so a typical goal stays intact
 * instead of being chopped mid-word by `truncate`.
 */
const SUBAGENT_GOAL_TITLE_MAX = 48;

export interface GroupHeaderLabelProps {
    /** Activity summary ("联网搜索 5 次 · 读 2 文件"); '' for a pure-reasoning episode. */
    activityText: string;
    /** Subagent context when this group is an exploded subagent segment. */
    subagent?: { goal: string; idx: number };
    /** True while this group is the live tail episode (drives 正在/已). */
    running: boolean;
}

export function GroupHeaderLabel({ activityText, subagent, running }: GroupHeaderLabelProps) {
    const localize = useLocalize();

    let label: string;
    if (subagent) {
        // R3 完全拆平: a subagent segment is headed by its delegation GOAL. The goal
        // is the subagent's identity, so it OWNS the header line — show only its
        // GIST (firstLine), falling back to the activity summary and finally the
        // "子智能体 N" label for a goal-less (degraded) subagent.
        const goalGist = firstLine(subagent.goal, SUBAGENT_GOAL_TITLE_MAX);
        label = goalGist || activityText || localize('com_linsight_subagent_track', { 0: String(subagent.idx) });
    } else if (activityText) {
        // Activity-summary header (verbs + counts), the primary case.
        label = activityText;
    } else {
        // Pure-reasoning fallback: the compact 深度思考 label. The `_compact`
        // variants are the duration-free wording, which is now the only wording —
        // the "（用时 N 秒）" pair they were the counterpart to no longer renders.
        label = localize(
            running ? 'com_linsight_deep_thinking_running_compact' : 'com_linsight_deep_thinking_done_compact',
        );
    }

    return <>{label}</>;
}

GroupHeaderLabel.displayName = 'GroupHeaderLabel';
