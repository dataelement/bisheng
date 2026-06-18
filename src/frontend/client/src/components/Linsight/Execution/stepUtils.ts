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
 * The Wave2 timeline node union consumed by ExecutionTimeline / SubagentTrack.
 * A `subagent_group` is the same shape buildFlowNodes already emits (preserved
 * verbatim, so the 22→3 grouping is untouched); a `deep_step_group` wraps a run
 * of consecutive top-level steps. The `step` member is kept in the union for
 * type-compat / defensive callers, but buildTimelineGroups never emits a bare
 * `step` — every top-level step is wrapped in a deep_step_group for uniform
 * rendering (decision pinned in stepUtils.test.ts).
 */
export type TimelineNode = DeepStepGroup | SubagentGroup | { kind: 'step'; step: MergedStep };

/**
 * (A) Distil a one-line fingerprint from a step's output: first sentence / line,
 * newlines stripped, trimmed, truncated to ~24 chars with an ellipsis. Empty
 * input returns an empty string (caller falls back to a localized label).
 */
const FIRST_LINE_MAX = 24;
export function firstLine(text: string | null | undefined): string {
    if (!text) return '';
    // collapse all whitespace runs (incl. newlines) to single spaces, then trim
    const flat = text.replace(/\s+/g, ' ').trim();
    if (!flat) return '';
    // prefer the first sentence boundary (CJK 。！？ or ASCII .!?) when it lands
    // inside the budget, otherwise hard-truncate
    const sentence = flat.match(/^.*?[。！？.!?]/);
    const head = sentence && sentence[0].length <= FIRST_LINE_MAX ? sentence[0] : flat;
    if (head.length <= FIRST_LINE_MAX) return head;
    return head.slice(0, FIRST_LINE_MAX) + '…';
}

/** Merge raw start/end frames by call_id, preserving first-seen order. */
export function mergeStepFrames(history: ExecStepEventData[] | null | undefined): MergedStep[] {
    const byId = new Map<string, MergedStep>();
    const order: string[] = [];

    (history || []).forEach((frame, idx) => {
        if (!frame || frame.step_type === 'call_user_input') return; // user-input handled by ClarifyCard/IntentRow
        // `ask_user` is the HITL interrupt mechanism, surfaced as a ClarifyCard /
        // IntentRow — not a normal tool step. Its tool-call frame emits a `start`
        // but never an `end` (interrupt() halts the graph), so rendering it as a
        // ToolRow would spin forever. Drop it.
        // `ls` is the agent's internal workspace exploration (typically empty at
        // the start of a no-upload task) — display noise, not a deliverable step.
        if (frame.name === 'ask_user' || frame.name === 'ls') return;
        const callId = frame.call_id || `__step_${idx}`;
        const ts = typeof frame.timestamp === 'number' ? frame.timestamp : undefined;
        const existing = byId.get(callId);
        if (!existing) {
            byId.set(callId, {
                callId,
                taskId: frame.task_id || '',
                name: frame.name || '',
                stepType: frame.step_type || 'tool',
                running: frame.status !== 'end',
                callReason: frame.call_reason || '',
                params: frame.params || null,
                output: frame.output || '',
                // The backend ships the subgraph namespace nested in
                // extra_info.namespace (ExecStep has no top-level `namespace`
                // field — see stream_event_mapper). Read it from there; keep the
                // top-level `frame.namespace` as a legacy fallback for fixtures.
                namespace: frame.extra_info?.namespace ?? frame.namespace ?? null,
                extraInfo: frame.extra_info || {},
                // first-seen frame timestamp starts the clock; end/later frames
                // extend endedAt below
                startedAt: ts,
                endedAt: ts,
                raw: frame,
            });
            order.push(callId);
            return;
        }
        // later frame for the same call: end frame closes the step; outputs of
        // streaming (thinking) frames are appended defensively
        if (frame.status === 'end') existing.running = false;
        if (frame.params && Object.keys(frame.params).length) existing.params = frame.params;
        if (frame.output) {
            existing.output =
                existing.output && frame.output !== existing.output
                    ? existing.output + frame.output
                    : frame.output;
        }
        if (frame.extra_info) existing.extraInfo = { ...existing.extraInfo, ...frame.extra_info };
        if (ts !== undefined) {
            if (existing.startedAt === undefined) existing.startedAt = ts;
            existing.endedAt = ts;
        }
        existing.raw = frame;
    });

    return order.map((id) => byId.get(id)!);
}

/**
 * (C) Merge consecutive thinking steps that share the same namespace (null==null
 * counts as same) into one rendered thinking step. The backend persists thinking
 * as many tiny token-delta frames (technical debt; see §7 open decision 1) — the
 * render layer stitches the adjacent ones back into a single passage:
 * - output concatenated SEAMLESSLY ("") — each delta already carries its own
 *   leading space and the model's own newlines, so a "\n\n" separator would
 *   shatter one continuous reasoning into a blank-line-per-token "poem".
 * - startedAt = earliest, endedAt = latest, running = last item's running
 * - callId taken from the first item (stable react key)
 * Thinking across different namespaces is NOT merged (avoid cross-subagent
 * contamination). Non-thinking steps pass through untouched and break a run.
 */
export function mergeAdjacentThinking(steps: MergedStep[]): MergedStep[] {
    const out: MergedStep[] = [];
    for (const step of steps) {
        const prev = out[out.length - 1];
        if (
            prev &&
            step.stepType === 'thinking' &&
            prev.stepType === 'thinking' &&
            prev.namespace === step.namespace
        ) {
            // fold into prev — clone first so we never mutate the input array
            const merged: MergedStep = out[out.length - 1] === prev ? { ...prev } : prev;
            merged.output = [merged.output, step.output].filter(Boolean).join('');
            if (step.startedAt !== undefined) {
                merged.startedAt =
                    merged.startedAt === undefined ? step.startedAt : Math.min(merged.startedAt, step.startedAt);
            }
            if (step.endedAt !== undefined) {
                merged.endedAt =
                    merged.endedAt === undefined ? step.endedAt : Math.max(merged.endedAt, step.endedAt);
            }
            merged.running = step.running;
            merged.raw = step.raw;
            out[out.length - 1] = merged;
            continue;
        }
        out.push(step);
    }
    return out;
}

/**
 * (D) Build the renderable node list for one task. Subagent identity is decided
 * purely by the set of distinct subgraph namespaces (per §5 / open decision 2).
 *
 * The team group is materialized LAZILY — only once a real subagent step (a
 * distinct namespace) actually arrives:
 * - step_type==='subagent' (the main-graph `task` delegation, ns=None): records
 *   the delegation goal/name into a pending buffer; it NEVER pushes a node on its
 *   own. Eagerly emitting a group here left an empty `agents` array during the
 *   live window before children stream in — which crashed the renderer
 *   (`agents[0].step`) and showed a stray "0 subagents" / "task" row.
 * - namespaced step (subagent-internal tool/knowledge/thinking, ns=tools:<uuid>):
 *   the first one materializes the group (consuming the pending goals); each
 *   distinct ns becomes one agent (so 3 distinct ns yield agents.length === 3,
 *   NOT 22). Later steps of a known ns append to that agent's children — even if
 *   a top-level step intervened (agentByNamespace persists for the whole task).
 * - top-level step (ns=None, not subagent): render inline and close the current
 *   delegation burst so the NEXT distinct ns starts a fresh group. The main graph
 *   is blocked while subagents run, so top-level steps only fall between rounds.
 */
export function buildFlowNodes(steps: MergedStep[]): FlowNode[] {
    const merged = mergeAdjacentThinking(steps);
    const nodes: FlowNode[] = [];
    // ns -> agent bucket; persists for the whole task so a subagent's later steps
    // always find their agent, even across an intervening top-level step.
    const agentByNamespace = new Map<string, SubagentAgent>();
    // Lazily-materialized current team group + the pending delegation metadata
    // collected from `task` frames that haven't been bound to a group yet.
    // `pendingDelegation` gates group creation: a namespaced step only forms a
    // team group when a real `task` delegation preceded it in this burst — a lone
    // namespaced step with no delegation context stays inline (defensive orphan).
    let currentGroup: SubagentGroup | null = null;
    let pendingGoals: string[] = [];
    let pendingName = '';
    let pendingDelegation = false;

    for (const step of merged) {
        // main-graph delegation point (B2): record goal/name only — no node yet.
        if (step.stepType === 'subagent') {
            const goal = step.callReason || step.extraInfo?.delegate_goal || '';
            if (currentGroup) {
                if (step.name) currentGroup.name = step.name;
                if (goal && !currentGroup.goals!.includes(goal)) currentGroup.goals!.push(goal);
            } else {
                pendingDelegation = true;
                if (step.name) pendingName = step.name;
                if (goal && !pendingGoals.includes(goal)) pendingGoals.push(goal);
            }
            continue;
        }

        // subagent-internal step: bucket by distinct namespace.
        if (step.namespace) {
            const known = agentByNamespace.get(step.namespace);
            if (known) {
                known.children.push(step);
                continue;
            }
            // first step of a new subagent — but only fold into a team group if a
            // delegation actually opened this burst; otherwise fall through to
            // inline (orphan namespaced step, defensive — shouldn't happen live).
            if (currentGroup || pendingDelegation) {
                if (!currentGroup) {
                    currentGroup = {
                        kind: 'subagent_group',
                        name: pendingName || step.name,
                        agents: [],
                        goals: pendingGoals,
                    };
                    nodes.push(currentGroup);
                    pendingGoals = [];
                    pendingName = '';
                    pendingDelegation = false;
                }
                const agent: SubagentAgent = { step, children: [], idx: currentGroup.agents.length + 1 };
                currentGroup.agents.push(agent);
                agentByNamespace.set(step.namespace, agent);
                continue;
            }
        }

        // top-level step (ns=None, not a delegation) or orphan namespaced step:
        // render inline + close the current burst so the next distinct ns opens a
        // fresh group (the main graph is blocked while subagents run).
        nodes.push({ kind: 'step', step });
        currentGroup = null;
        pendingGoals = [];
        pendingName = '';
        pendingDelegation = false;
    }

    return nodes;
}

/**
 * (Wave2 / F2b) Aggregate the flow nodes ONE level higher, so the task-mode
 * timeline reads like the daily-chat "deep thinking" surface:
 * - run buildFlowNodes (keeps the 22→3 subagent_group grouping untouched);
 * - wrap each maximal run of consecutive `{ kind: 'step' }` nodes into a single
 *   `deep_step_group` (thinking + tool + knowledge in one collapsible episode);
 * - a `subagent_group` breaks the run and passes through verbatim.
 *
 * A lone top-level step is ALSO wrapped in a deep_step_group (uniform rendering
 * — ExecutionTimeline only has to dispatch two node kinds). buildTimelineGroups
 * accepts ANY MergedStep[]: when SubagentTrack drills into a single subagent's
 * `children` (pure thinking + tool, no delegation frame, no namespace flip) the
 * whole input collapses to deep_step_groups, giving the same render primitive
 * for the L3 drill-down.
 */
export function buildTimelineGroups(steps: MergedStep[]): TimelineNode[] {
    const flow = buildFlowNodes(steps);
    const out: TimelineNode[] = [];
    // open episode being accumulated; flushed when a subagent_group breaks the
    // run or the input ends.
    let episode: MergedStep[] = [];

    const flush = () => {
        if (!episode.length) return;
        let startedAt: number | undefined;
        let endedAt: number | undefined;
        let running = false;
        for (const s of episode) {
            if (s.startedAt !== undefined) {
                startedAt = startedAt === undefined ? s.startedAt : Math.min(startedAt, s.startedAt);
            }
            if (s.endedAt !== undefined) {
                endedAt = endedAt === undefined ? s.endedAt : Math.max(endedAt, s.endedAt);
            }
            if (s.running) running = true;
        }
        out.push({ kind: 'deep_step_group', steps: episode, startedAt, endedAt, running });
        episode = [];
    };

    for (const node of flow) {
        if (node.kind === 'step') {
            episode.push(node.step);
            continue;
        }
        // subagent_group: close the current episode, then pass the group through.
        flush();
        out.push(node);
    }
    flush();

    return out;
}

/** True if a timeline node is still running (any agent / any step / the step). */
export function isTimelineNodeRunning(node: TimelineNode): boolean {
    if (node.kind === 'subagent_group') return node.agents.some((a) => a.step.running);
    if (node.kind === 'deep_step_group') return node.running;
    return node.step.running;
}

/** True if a flow node is still running (any agent for a group; the step otherwise). */
export function isFlowNodeRunning(node: FlowNode): boolean {
    return node.kind === 'subagent_group' ? node.agents.some((a) => a.step.running) : node.step.running;
}

/**
 * The flow node a collapsed task header should summarize: the last running node,
 * or the most recent node if none is running. Returns null for an empty history.
 */
export function activeFlowNode(history: ExecStepEventData[] | null | undefined): FlowNode | null {
    const nodes = buildFlowNodes(mergeStepFrames(history));
    if (!nodes.length) return null;
    for (let i = nodes.length - 1; i >= 0; i--) {
        if (isFlowNodeRunning(nodes[i])) return nodes[i];
    }
    return nodes[nodes.length - 1];
}

// ── clarify / user_input parsing ─────────────────────────────────────────────

/** One question page parsed from `user_input.data.params.tool_calls[].args`. */
export interface ClarifyQuestion {
    id: string;
    question: string;
    options: string[];
    multiple: boolean;
}

/** Parsed clarify request; `questions` empty => fall back to a plain textarea. */
export interface ClarifyRequest {
    taskId: string;
    callReason: string;
    questions: ClarifyQuestion[];
    raw: ExecStepEventData;
}

/**
 * Defensive parse of a `user_input` event payload (fixture shape:
 * data.params.tool_calls[{id, name, args:{question, options}}]). Anything
 * unparseable degrades to a free-text question (legacy UserInput shape).
 */
export function parseClarifyRequest(data: ExecStepEventData): ClarifyRequest {
    const callReason = data.call_reason || data.params?.call_title || '';
    const toolCalls = Array.isArray(data.params?.tool_calls) ? data.params!.tool_calls : [];

    const questions: ClarifyQuestion[] = [];
    toolCalls.forEach((tc: any, idx: number) => {
        const args = tc?.args || {};
        const question = typeof args.question === 'string' ? args.question : typeof args.title === 'string' ? args.title : '';
        if (!question) return;
        // Options are plain strings. Checkpoints parked before the is_default
        // feature was removed may still carry {text, ...} objects, so extract the
        // text defensively; the text is both the display label and answer value.
        const rawOptions = Array.isArray(args.options) ? args.options : [];
        const options: string[] = [];
        rawOptions.forEach((o: any) => {
            if (typeof o === 'string') {
                options.push(o);
            } else if (o && typeof o === 'object' && typeof o.text === 'string') {
                options.push(o.text);
            }
        });
        questions.push({
            id: String(tc?.id || `q_${idx}`),
            question,
            options,
            multiple: !!(args.multiple || args.multi_select || args.type === 'multi'),
        });
    });

    // legacy interrupt shape (params.call_title / call_content) => single free-text question
    if (!questions.length && data.params?.call_content) {
        questions.push({ id: 'q_legacy', question: String(data.params.call_content), options: [], multiple: false });
    }

    return { taskId: data.task_id || '', callReason, questions, raw: data };
}

/** Compose the structured answer text submitted through user-input API. */
export function composeClarifyAnswer(
    questions: ClarifyQuestion[],
    answers: Record<string, string[]>,
    skippedText: string,
): string {
    if (!questions.length) return answers.__free__?.join('') || '';
    return questions
        .map((q) => {
            const ans = answers[q.id];
            const text = ans && ans.length ? ans.join('、') : skippedText;
            return questions.length > 1 ? `${q.question}: ${text}` : text;
        })
        .join('\n');
}

// ── shared status helpers ────────────────────────────────────────────────────

export const TASK_DONE_STATUSES = ['success'];
export const TASK_RUNNING_STATUSES = ['in_progress', 'user_input', 'user_input_completed', 'waiting_for_user_input'];
export const TASK_ERROR_STATUSES = ['failed', 'terminated'];

export function isTaskDone(status?: string): boolean {
    return TASK_DONE_STATUSES.includes(status || '');
}

export function isTaskRunning(status?: string): boolean {
    return TASK_RUNNING_STATUSES.includes(status || '');
}

/**
 * A task is "started" once execution has actually reached it — running, finished,
 * or errored. Not-yet-reached tasks (e.g. `not_started`) must NOT appear in the
 * conversation step flow; they only show up in the TaskPanel checklist. The flow
 * reveals steps progressively as they are reached.
 */
export function isTaskStarted(status?: string): boolean {
    return isTaskRunning(status) || isTaskDone(status) || TASK_ERROR_STATUSES.includes(status || '');
}

/**
 * F035 (live vs refresh parity): the backend persists all session-level steps
 * (planning / thinking / write_todos / ask_user) inside a single "执行准备"
 * pseudo-task (``task_data.is_session_global``) so they survive a refresh — see
 * task_exec._ensure_session_pseudo_task. The LIVE flow instead keeps them in a
 * separate inline ``sessionSteps`` bucket and renders the answered clarify as an
 * "已经明确用户意图" IntentRow.
 *
 * To make the reloaded view match the live one, lift the pseudo-task's steps
 * back out: drop it from the rendered task list and expose its ``history`` as
 * the session steps (so they render inline + the clarify becomes an IntentRow).
 * Live steps win when present (active turn); the persisted history is used only
 * on reload. A no-op for sessions without the pseudo-task.
 */
export function splitSessionPseudoTask<T extends { task_data?: any; history?: ExecStepEventData[] }>(
    rawTasks: T[],
    liveSessionSteps: ExecStepEventData[],
): { tasks: T[]; sessionSteps: ExecStepEventData[] } {
    const pseudo = rawTasks.find((t) => t?.task_data?.is_session_global);
    if (!pseudo) return { tasks: rawTasks, sessionSteps: liveSessionSteps };
    return {
        tasks: rawTasks.filter((t) => t !== pseudo),
        sessionSteps: liveSessionSteps.length ? liveSessionSteps : pseudo.history || [],
    };
}
