/**
 * GroupHeaderLabel — the live "用时 N 秒" header text for a DeepStepGroup, split
 * out as its OWN component so the 100ms elapsed ticker re-renders ONLY this label,
 * never the group body (thinking passages + tool rows).
 *
 * Why the split (perf): useElapsedTicker fires a 100ms setInterval while the group
 * is the live tail. When the ticker lived in DeepStepGroup, every tick re-rendered
 * the whole group — its thinking <p> blocks and every ToolRowLite — ten times a
 * second, on top of the per-WS-frame timeline rebuild. That main-thread pressure
 * starved the timer callback and made the counter advance unevenly / skip seconds.
 * Isolating the ticker here means a tick touches only this one-line label; the
 * group body re-renders solely when its steps actually change (a real WS frame).
 *
 * The label math is unchanged from the old in-group useMemo (whole-second format,
 * the subagent-goal / activity-summary / pure-reasoning branches, the noDuration
 * gate), so the rendered text — and the DeepStepGroup label tests — are identical.
 */
import { useLocalize } from '~/hooks';
import { formatSeconds } from '~/utils';
import { firstLine } from './stepUtils';
import { useElapsedTicker } from './useElapsedTicker';

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
    /** Drilldown (inside a subagent card): drop the "（用时 N 秒）" clause. */
    compact: boolean;
    /** Group clock start/end in ms (null ⇒ no clock; caller scaled second→ms). */
    startMs: number | null;
    endMs: number | null;
    /** True while this group is the live tail episode (drives 正在/已 + the ticker). */
    running: boolean;
}

export function GroupHeaderLabel({ activityText, subagent, compact, startMs, endMs, running }: GroupHeaderLabelProps) {
    const localize = useLocalize();
    // Owns the 100ms live ticker. setTick re-renders THIS component only, so a
    // running group's "用时" advances without re-rendering the group body.
    const { elapsedMs } = useElapsedTicker(startMs, endMs, running);

    // No useMemo: elapsedMs advances on every 100ms tick (and reads Date.now()
    // fresh each render), so a memo keyed on it would never hit — the label is
    // recomputed every render regardless. Inline string-building is cheaper.
    const seconds = formatSeconds(elapsedMs);
    // Drop the duration clause when nested (compact) OR when the measured span is 0
    // (a single second-level frame would read a misleading "用时 0 秒").
    const noDuration = compact || elapsedMs <= 0;
    let label: string;
    if (subagent) {
        // R3 完全拆平: a subagent segment is headed by its delegation GOAL + 用时.
        // The goal is the subagent's identity, so it OWNS the header line — show
        // only its GIST (firstLine), falling back to the activity summary and
        // finally the "子智能体 N" label for a goal-less (degraded) subagent.
        const goalGist = firstLine(subagent.goal, SUBAGENT_GOAL_TITLE_MAX);
        const core = goalGist || activityText || localize('com_linsight_subagent_track', { 0: String(subagent.idx) });
        label = noDuration ? core : localize('com_linsight_act_summary', { 0: core, 1: seconds });
    } else if (activityText) {
        // Activity-summary header (verbs + counts), the primary case.
        label = noDuration ? activityText : localize('com_linsight_act_summary', { 0: activityText, 1: seconds });
    } else if (noDuration) {
        // Pure-reasoning fallback (no measurable span): the compact 深度思考 label.
        label = localize(
            running ? 'com_linsight_deep_thinking_running_compact' : 'com_linsight_deep_thinking_done_compact',
        );
    } else {
        // Pure-reasoning fallback with a duration.
        label = localize(
            running ? 'com_linsight_deep_thinking_running' : 'com_linsight_deep_thinking_done',
            { 0: seconds },
        );
    }

    return <>{label}</>;
}

GroupHeaderLabel.displayName = 'GroupHeaderLabel';
