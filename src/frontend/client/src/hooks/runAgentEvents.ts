/**
 * F004 — thinking segments and tool calls of a run as the ordered event log
 * the answer bubble renders. No React, no HTTP.
 *
 * The answer row is rebuilt for every delta of the run, so this is on the hot
 * path. Three rules keep a long answer cheap:
 *   - a text delta changes neither `run.thinking` nor `run.toolCalls` (the
 *     reducer keeps both arrays), so the list of the previous call is returned
 *     as it is: same array, nothing rebuilt;
 *   - a thinking delta or a tool call frame replaces one segment or one call.
 *     Only that item gets a new event object; every other item keeps the object
 *     it had, so the bubbles of the other items do not render again;
 *   - both arrays are already in arrival order, so they are merged, not sorted.
 *
 * The caches are WeakMaps keyed by the store's own objects. They hold nothing
 * once the run state that owns those objects is gone.
 */
import type { AgentEvent } from '~/api/chatApi';
import type { RunState, RunToolCall, ThinkingSegment } from '~/store/runStore';

const thinkingEvents = new WeakMap<ThinkingSegment, AgentEvent>();
const toolCallEvents = new WeakMap<RunToolCall, AgentEvent>();
/** Key: `run.toolCalls`. Valid while `run.thinking` is the array it was built with. */
const eventLists = new WeakMap<RunToolCall[], { thinking: ThinkingSegment[]; events: AgentEvent[] }>();

function eventOfThinking(segment: ThinkingSegment): AgentEvent {
    let event = thinkingEvents.get(segment);
    if (!event) {
        event = { type: 'thinking', content: segment.text };
        thinkingEvents.set(segment, event);
    }
    return event;
}

function eventOfToolCall(call: RunToolCall): AgentEvent {
    let event = toolCallEvents.get(call);
    if (!event) {
        const displayName = call.extraInfo?.display_name;
        const args =
            call.params && typeof call.params === 'object' && !Array.isArray(call.params)
                ? (call.params as Record<string, unknown>)
                : call.params == null
                  ? undefined
                  : { input: call.params };
        event = {
            type: 'tool_call',
            tool_call_id: call.callId,
            tool_name: call.name,
            ...(typeof displayName === 'string' && displayName ? { display_name: displayName } : {}),
            tool_type: call.stepType,
            ...(args ? { args } : {}),
            ...(call.output != null ? { results: call.output } : {}),
            inflight: call.status === 'running',
        };
        toolCallEvents.set(call, event);
    }
    return event;
}

/**
 * Thinking segments and tool calls of a run in arrival order (`order`); on an
 * equal rank the thinking segment comes first. The returned array and its
 * items are shared between calls: callers must not change them.
 */
export function agentEventsOfRun(run: RunState): AgentEvent[] {
    const { thinking, toolCalls } = run;
    const cached = eventLists.get(toolCalls);
    if (cached && cached.thinking === thinking) return cached.events;
    const events: AgentEvent[] = [];
    let t = 0;
    let c = 0;
    while (t < thinking.length || c < toolCalls.length) {
        const takeThinking =
            c >= toolCalls.length || (t < thinking.length && (thinking[t].order ?? 0) <= (toolCalls[c].order ?? 0));
        events.push(takeThinking ? eventOfThinking(thinking[t++]) : eventOfToolCall(toolCalls[c++]));
    }
    eventLists.set(toolCalls, { thinking, events });
    return events;
}
