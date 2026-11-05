import { SopStatus } from '~/store/linsight';

interface ToolApi { id: string | number; name: string; tool_key: string; desc?: string }
interface ToolSelection {
    id: string; checked?: boolean;
    data?: { id: string | number; name: string; is_preset?: boolean; description?: string; children?: ToolApi[] };
}
interface TaskRow {
    id: string; name?: string; status: string; history?: unknown[]; input_prompt?: string;
    task_data?: { name?: string; display_target?: string; is_session_global?: boolean };
    result?: { answer?: string }; children?: TaskRow[];
}

export const convertTools = (tools: ToolSelection[]) => {
    let org_knowledge_enabled = false
    let personal_knowledge_enabled = false

    const sopTools: NonNullable<ToolSelection['data']>[] = []
    tools.forEach(tool => {
        if (tool.checked && tool.id === 'pro_knowledge') {
            org_knowledge_enabled = true
        } else if (tool.checked && tool.id === 'knowledge') {
            personal_knowledge_enabled = true
        } else if (tool.checked) {
            const { id, name, is_preset, description, children = [] } = tool.data!
            sopTools.push({
                id,
                name,
                is_preset,
                description,
                children: children.map(api => {
                    return {
                        id: api.id,
                        name: api.name,
                        tool_key: api.tool_key,
                        desc: api.desc
                    }
                })
            })
        }
    });

    return {
        org_knowledge_enabled,
        personal_knowledge_enabled,
        tools: sopTools
    }
}


/**
 * Map a backend session-version status (SessionVersionStatusEnum) to the
 * frontend SopStatus used by the store. Centralised so the reload path
 * (switchAndUpdateLinsight) agrees with the live WS pump on what "running" means.
 *
 * `not_started` means the session has been submitted + enqueued but the Linsight
 * worker has not picked it up yet (it flips to `in_progress` only on dequeue, in
 * task_exec._execute_workflow) — i.e. it is QUEUED. The F035 client has no manual
 * "start" affordance, so `not_started` is never a resting SOP state here; it must
 * map to Running so the queue polling stays enabled and <QueueCard> survives a
 * refresh / session switch (otherwise `running` is false and the 排队中 badge is
 * lost). A genuinely non-queued not_started degrades gracefully: queue-status
 * returns index 0, so no phantom card shows.
 *
 * `waiting_for_user_input` is a dedicated backend state (park-and-release HITL):
 * the run is parked on an ask_user interrupt, not finished. The live flow never
 * leaves SopStatus.Running while parked (the WS `user_input` event only changes
 * the task's status, not the session's), so on reload it MUST also map to Running
 * — otherwise `running` is false, the ClarifyCard / waiting input is gated off,
 * and the user sees no input prompt after a refresh.
 */
export function mapSessionVersionStatus(status: string, executeFeedback?: string | null): string {
    switch (status) {
        case 'sop_generation_failed':
            return SopStatus.SopGenerated;
        case 'not_started':
        case 'in_progress':
        case 'waiting_for_user_input':
            return SopStatus.Running;
        case 'completed':
            return executeFeedback ? SopStatus.FeedbackCompleted : SopStatus.completed;
        case 'terminated':
        case 'failed':
            return SopStatus.Stoped;
        default:
            return status; // unknown status passes through unchanged
    }
}

/**
 * Project the server's task rows onto the shape the panels render.
 *
 * Status is passed through as-is. There used to be a sticky `hasTerminated` flag
 * here that rewrote EVERY row after the first `terminated`/`failed` one to
 * `not_started` (to hide them), back when `terminated` could only mean "the user
 * hit stop". It no longer can: `_diff_todos` now also marks a todo `terminated` when
 * the MODEL prunes it from its own plan, so one pruned todo silently buried every
 * task after it — a session with 8 successful tasks rendered "3/18" with grey
 * rings, and since `isTaskStarted('not_started')` is false, those tasks' steps
 * vanished from the timeline too.
 *
 * Nothing is lost by passing status through: a manually stopped run has its
 * unfinished rows swept to TERMINATED by the backend (`_terminate_unfinished_tasks`)
 * and its in-flight row rewritten by `getLinsightTaskList`, `TaskPanel` keys the
 * stopped-run rendering off its own `terminated` prop, and a pruned row with no
 * history is dropped by TaskStepRow's empty guard. The live WS path never called
 * this function at all — so this is the reload view converging on the live one.
 */
export function buildTaskTree(tasks: TaskRow[]) {
    const newTasks = tasks.map(task => {
        const taskTree = {
            id: task.id,
            // F035 deepagents tasks carry the title at task_data.name; tolerate a
            // flat name / legacy display_target too. MUST match the live WS
            // task_generate mapping (Websocket/index.tsx) or history-loaded turns
            // render blank task rows (structure present, names empty).
            name: task.name || task.task_data?.name || task.task_data?.display_target || '',
            status: task.status === 'waiting_for_user_input' ? 'user_input' : task.status,
            history: task.history || [],
            event_type: task.status === 'waiting_for_user_input' ? 'user_input' : '',
            call_reason: task.input_prompt || '',
            errorMsg: task.result?.answer || '',
            // Preserve task_data so splitSessionPseudoTask / PinnedTaskPanel can
            // recognize the session-global "执行准备" pseudo task (is_session_global)
            // on reload and lift its steps out, instead of rendering it as a task row.
            task_data: task.task_data,
            children: task.children?.map(child => {
                return {
                    id: child.id,
                    name: child.name || child.task_data?.name || child.task_data?.display_target || '',
                    status: child.status === 'waiting_for_user_input' ? 'user_input' : child.status,
                    history: child.history || [],
                    event_type: child.status === 'waiting_for_user_input' ? 'user_input' : '',
                    call_reason: '',
                    task_data: child.task_data
                }
            }) || []
        }

        return taskTree
    })
    return newTasks

}
