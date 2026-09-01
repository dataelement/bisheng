/**
 * F035 Track H (P3): pure helpers that turn the raw WS event log
 * (task.history / linsight.sessionSteps) into a renderable step tree.
 * Data truth: src/backend/test/linsight/fixtures/ws_events/{event_samples,step_types}.json
 * - task_execute_step frames are merged by call_id (start + end -> one step)
 * - the persisted history frame is ExecStep.model_dump() — namespace is nested
 *   in extra_info.namespace and the second-level int timestamp is top-level.
 *
 * Render contract after backend B1+B2 (《灵思任务模式执行流渲染优化方案》§5):
 * - thinking frame: step_type='thinking', name='thinking'; extra_info.namespace
 *   carries the flat subgraph ns (tools:<uuid>) when emitted inside a subagent.
 * - subagent-internal tool/knowledge frame: step_type inferred by name (B1
 *   dropped the `if ns: return "subagent"` line), extra_info.namespace=tools:<uuid>.
 * - main-graph `task` delegation frame (the ONLY source of step_type='subagent'
 *   after B2): ns=None, name=subagent_type (default 'general-purpose'),
 *   call_reason / extra_info.delegate_goal = the delegation goal.
 * - the delegation frame (ns=None) and a subagent's sub-steps (ns=tools:<uuid>)
 *   share NO namespace string (no B3 precise correlation): subagent identity is
 *   decided purely by the set of distinct subgraph namespaces.
 */

export type ExecStepType = 'tool' | 'thinking' | 'knowledge' | 'subagent' | 'ui_card' | 'call_user_input';

/**
 * Attachment ingest moved off the submit request into the worker, so the parse
 * now happens while the task is already claimed. The worker reports it as an
 * ordinary tool row carrying only DATA — the wording lives here, because a
 * backend-formatted label would show Chinese to a Japanese user and would stay
 * wrong in persisted history after a language switch.
 *
 * ⚠️ Contract with the backend: this name is `_INGEST_STEP_NAME` in
 * bisheng/linsight/domain/task_exec.py. Change one side alone and the row falls
 * back to rendering the raw token.
 */
export const INGEST_STEP_NAME = 'ingest_uploads';

export type IngestPhase = 'running' | 'done' | 'failed' | 'aborted';

export interface IngestProgress {
    phase: IngestPhase;
    done: number;
    total: number;
    fileName?: string;
}

/** phase → i18n key, same shape as ACTIVITY_I18N in execTokens. */
export const INGEST_PHASE_I18N: Record<IngestPhase, string> = {
    running: 'com_linsight_ingest_running',
    done: 'com_linsight_ingest_done',
    failed: 'com_linsight_ingest_failed',
    aborted: 'com_linsight_ingest_aborted',
};

const INGEST_PHASES = Object.keys(INGEST_PHASE_I18N) as IngestPhase[];

/** Pull the ingest payload off a step, or null when it is not an ingest row.
    Defensive about every field: this crosses a process boundary, and an older
    worker emits nothing here at all. */
export function readIngestProgress(step: {
    name?: string;
    extraInfo?: Record<string, unknown>;
}): IngestProgress | null {
    if (step.name !== INGEST_STEP_NAME) return null;
    const raw = step.extraInfo?.ingest_progress;
    if (!raw || typeof raw !== 'object') return null;
    const payload = raw as Record<string, unknown>;
    return {
        phase: INGEST_PHASES.find((p) => p === payload.phase) ?? 'running',
        done: Number(payload.done) || 0,
        total: Number(payload.total) || 0,
        fileName: typeof payload.file_name === 'string' ? payload.file_name : undefined,
    };
}

/**
 * A skill the user picked could not be loaded for this run.
 *
 * Skill bundles live in object storage and are materialized per run; when that
 * fails the task still runs, just without the skill. Left unreported this is
 * indistinguishable from never having selected it — which is exactly how the old
 * local-disk storage hid a multi-node inconsistency for months.
 *
 * ⚠️ Contract with the backend: `_SKILL_LOAD_FAILED_STEP_NAME` in
 * bisheng/linsight/domain/task_exec.py.
 */
export const SKILL_LOAD_FAILED_STEP_NAME = 'skill_load_failed';

/** Pull the failed skill names off a step, or null when it is not that row. */
export function readSkillLoadFailure(step: {
    name?: string;
    extraInfo?: Record<string, unknown>;
}): string[] | null {
    if (step.name !== SKILL_LOAD_FAILED_STEP_NAME) return null;
    const raw = step.extraInfo?.skill_load_failed;
    if (!raw || typeof raw !== 'object') return null;
    const names = (raw as Record<string, unknown>).names;
    if (!Array.isArray(names)) return null;
    const cleaned = names.filter((n): n is string => typeof n === 'string' && n.length > 0);
    return cleaned.length ? cleaned : null;
}

/** Raw `task_execute_step.data` frame (contract C1). */
export interface ExecStepEventData {
    call_id?: string;
    task_id?: string;
    name?: string;
    step_type?: ExecStepType | string;
    status?: 'start' | 'end' | string;
    call_reason?: string | null;
    params?: Record<string, any> | null;
    output?: string | null;
    namespace?: string | null;
    extra_info?: Record<string, any> | null;
    /** Second-level int timestamp stamped on every ExecStep (BaseEvent.timestamp). */
    timestamp?: number;
    /** Locally stamped by the clarify flow (legacy contract kept for Sop view). */
    is_completed?: boolean;
    user_input?: string;
    [key: string]: any;
}

/** A start/end-merged step ready for rendering. */
export interface MergedStep {
    callId: string;
    taskId: string;
    name: string;
    stepType: string;
    /** true until the matching `status: 'end'` frame arrives */
    running: boolean;
    callReason: string;
    params: Record<string, any> | null;
    /** thinking steps stream output across frames — concatenated here */
    output: string;
    namespace: string | null;
    extraInfo: Record<string, any>;
    /** second-level timestamp of the first frame seen for this call */
    startedAt?: number;
    /** second-level timestamp of the latest frame seen (end frame when closed) */
    endedAt?: number;
    raw: ExecStepEventData;
}

/** One delegated subagent: its anchor/first step plus the steps it emitted. */
export interface SubagentAgent {
    step: MergedStep;
    /** child steps emitted under this agent's namespace */
    children: MergedStep[];
    /** 1-based position within the team group (display order) */
    idx?: number;
}

/**
 * A delegation group: one main-graph `task` delegation point plus the distinct
 * subgraph namespaces (the real subagents) that ran under it. `name` is the
 * subagent type; `goals` collects each delegation's goal for the group header.
 */
export interface SubagentGroup {
    kind: 'subagent_group';
    name: string;
    agents: SubagentAgent[];
    /** delegation goals collected from `task` frames (call_reason/delegate_goal) */
    goals?: string[];
}

export type FlowNode = { kind: 'step'; step: MergedStep } | SubagentGroup;

/**
 * (R3 完全拆平 2026-06) One subagent rendered as its OWN top-level segment, with
 * no team shell. After backend B2 the subagent's internal steps already ride the
 * single stream (identified by namespace, not task_id); the render layer explodes
 * the namespace-grouped {@link SubagentGroup} into one flat segment per subagent.
 * `goal` is a best-effort delegation goal (order-aligned with the delegation
 * burst; '' when the burst's goal count doesn't match the agent count).
 */
export interface SubagentSegment {
    kind: 'subagent_segment';
    /** best-effort delegation goal, '' when unknown */
    goal: string;
    /** 1-based index within the original burst (for the "子智能体 N" fallback) */
    idx: number;
    /** the subagent's flattened steps (anchor + same-ns children), in order */
    steps: MergedStep[];
    startedAt?: number;
    endedAt?: number;
    running: boolean;
}


/**
 * (Wave2) A "deep thinking" episode: one continuous run of top-level (non
 * subagent_group, non-orphan) steps — thinking + tool + knowledge — aggregated
 * into a single collapsible group, isomorphic to the daily-chat DeepThinkingGroup.
 * The inner thinking passages are joined with a blank line at render time; here
 * we only carry the ordered steps plus the group-level time range.
 */
export interface DeepStepGroup {
    kind: 'deep_step_group';
    /** ordered steps in this episode (thinking + tool + knowledge), as built */
    steps: MergedStep[];
    /** earliest startedAt across the steps (group clock start) */
    startedAt?: number;
    /** latest endedAt across the steps (group clock end) */
    endedAt?: number;
    /** true while ANY step in the episode is still running */
    running: boolean;
}

/**
 * An answered clarify (call_user_input + is_completed) rendered INLINE at its
 * chronological position in the timeline (not hoisted to the panel top). It cuts
 * the surrounding thinking into the episode BEFORE the question and the resumed
 * episode AFTER it, so the flow reads 思考A → 已明确意图 → 思考B in real order.
 * Carries the raw frame for IntentRow (parseClarifyRequest reads params/user_input)
 * plus the frame timestamp so the duration-repair pass can order around it.
 */
export interface IntentNode {
    kind: 'intent';
    data: ExecStepEventData;
    /** frame second-level timestamp — lets nodeStart() order this node */
    startedAt?: number;
}

/**
 * The Wave2 timeline node union consumed by ExecutionTimeline. A `subagent_group`
 * is the same shape buildFlowNodes already emits (preserved verbatim; the render
 * layer explodes it into per-subagent segments — see explodeSubagentGroup); a
 * `deep_step_group` wraps a run
 * of consecutive top-level steps; an `intent` node is an inline answered clarify
 * (see IntentNode). The `step` member is kept in the union for
 * type-compat / defensive callers, but buildTimelineGroups never emits a bare
 * `step` — every top-level step is wrapped in a deep_step_group for uniform
 * rendering (decision pinned in stepUtils.test.ts).
 */
export type TimelineNode = DeepStepGroup | SubagentGroup | IntentNode | { kind: 'step'; step: MergedStep };
