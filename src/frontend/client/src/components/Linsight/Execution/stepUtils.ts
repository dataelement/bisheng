/**
 * F035 Track H (P3): pure helpers that turn the raw WS event log
 * (task.history / linsight.sessionSteps) into a renderable step tree.
 * Data truth: src/backend/test/linsight/fixtures/ws_events/{event_samples,step_types}.json
 * - task_execute_step frames are merged by call_id (start + end -> one step)
 * - steps with a non-null namespace belong to the subagent step that declared
 *   that namespace; consecutive subagent steps with the same name are grouped
 *   into one delegation row with N cards
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
    raw: ExecStepEventData;
}

/** A delegation group: consecutive subagent steps sharing the same name. */
export interface SubagentGroup {
    kind: 'subagent_group';
    name: string;
    agents: {
        step: MergedStep;
        /** child steps emitted under this agent's namespace */
        children: MergedStep[];
    }[];
}

export type FlowNode = { kind: 'step'; step: MergedStep } | SubagentGroup;

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
        existing.raw = frame;
    });

    return order.map((id) => byId.get(id)!);
}

/**
 * Build the renderable node list for one task:
 * top-level steps stay inline; namespaced steps are attached to the subagent
 * step that owns the namespace; consecutive same-name subagents are grouped.
 */
export function buildFlowNodes(steps: MergedStep[]): FlowNode[] {
    const nodes: FlowNode[] = [];
    // namespace -> agent bucket, so children can find their owner
    const agentByNamespace = new Map<string, { step: MergedStep; children: MergedStep[] }>();

    for (const step of steps) {
        if (step.stepType === 'subagent') {
            const agent = { step, children: [] as MergedStep[] };
            if (step.namespace) agentByNamespace.set(step.namespace, agent);
            const last = nodes[nodes.length - 1];
            if (last && last.kind === 'subagent_group' && last.name === step.name) {
                last.agents.push(agent);
            } else {
                nodes.push({ kind: 'subagent_group', name: step.name, agents: [agent] });
            }
            continue;
        }

        if (step.namespace) {
            // child of a delegated agent — exact match first, then prefix match
            // for deeper sub-graph levels ("ns:0:..." belongs to "ns:0")
            const owner =
                agentByNamespace.get(step.namespace) ||
                [...agentByNamespace.entries()].find(([ns]) => step.namespace!.startsWith(ns))?.[1];
            if (owner) {
                owner.children.push(step);
                continue;
            }
            // defensive: orphan namespaced step falls back to inline rendering
        }

        nodes.push({ kind: 'step', step });
    }

    return nodes;
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
        const options = Array.isArray(args.options) ? args.options.filter((o: any) => typeof o === 'string') : [];
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
