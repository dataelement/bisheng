/**
 * appendStepFrame (ingest-time fold) must be render-invisible: for any frame
 * sequence, merging the folded history yields the same steps and the same
 * timeline as merging the raw frame log. Checked on every streaming prefix,
 * because the live view renders each prefix, not only the final log.
 */
import persisted from './__fixtures__/linsightSieyuanPptHistory.json';
import type { ExecStepEventData, MergedStep } from './stepUtils';
import { appendStepFrame, buildTimelineGroups, mergeStepFrames } from './stepUtils';

type Comparable = Omit<MergedStep, 'raw'>;

// `raw` is read only for call_user_input steps (never folded: no call_id); a
// synthetic `__step_<idx>` id depends on the log position, which folding shrinks.
function comparable(steps: MergedStep[]): Comparable[] {
    return steps.map(({ raw, ...rest }) => ({
        ...rest,
        callId: rest.callId.startsWith('__step_') ? '__step_' : rest.callId,
        ...(rest.stepType === 'call_user_input' ? { rawCompleted: !!raw.is_completed } : {}),
    }));
}

function timelineShape(history: ExecStepEventData[]): unknown {
    return buildTimelineGroups(mergeStepFrames(history)).map((node) => {
        if (node.kind === 'deep_step_group') {
            return { ...node, steps: comparable(node.steps) };
        }
        if (node.kind === 'subagent_group') {
            return {
                ...node,
                agents: node.agents.map((a) => ({
                    idx: a.idx,
                    step: comparable([a.step])[0],
                    children: comparable(a.children),
                })),
            };
        }
        if (node.kind === 'intent') return { kind: 'intent', startedAt: node.startedAt };
        return { kind: node.kind, step: comparable([node.step])[0] };
    });
}

function fold(frames: ExecStepEventData[]): ExecStepEventData[] {
    let history: ExecStepEventData[] = [];
    for (const f of frames) history = appendStepFrame(history, f);
    return history;
}

function expectEquivalentOnEveryPrefix(frames: ExecStepEventData[], stride = 1) {
    let folded: ExecStepEventData[] = [];
    for (let i = 0; i < frames.length; i++) {
        folded = appendStepFrame(folded, frames[i]);
        if ((i + 1) % stride !== 0 && i !== frames.length - 1) continue;
        const raw = frames.slice(0, i + 1);
        expect(comparable(mergeStepFrames(folded))).toEqual(comparable(mergeStepFrames(raw)));
        expect(timelineShape(folded)).toEqual(timelineShape(raw));
    }
}

/** Re-explode a persisted (one-entry-per-call_id) history into a live frame log. */
function explode(history: ExecStepEventData[]): ExecStepEventData[] {
    const out: ExecStepEventData[] = [];
    for (const entry of history) {
        if (entry.step_type === 'thinking' && entry.output) {
            const text = entry.output;
            const ts = entry.timestamp ?? 0;
            for (let i = 0; i < text.length; i += 7) {
                out.push({ ...entry, output: text.slice(i, i + 7), timestamp: ts + Math.floor(i / 70) });
            }
            continue;
        }
        if (entry.step_type === 'tool' && entry.status === 'end') {
            out.push({ ...entry, status: 'start', output: '', timestamp: (entry.timestamp ?? 1) - 1 });
        }
        out.push(entry);
    }
    return out;
}

describe('appendStepFrame — fold is render-invisible', () => {
    it('history length tracks steps, not token frames', () => {
        const frames = explode(persisted as ExecStepEventData[]);
        expect(frames.length).toBeGreaterThan(persisted.length * 5);
        expect(fold(frames)).toHaveLength(persisted.length);
    });

    it('matches the raw-log merge on a real session re-streamed token by token', () => {
        expectEquivalentOnEveryPrefix(explode(persisted as ExecStepEventData[]), 25);
    });

    it('matches the raw-log merge on interleaved tools, subagents, clarify and edge frames', () => {
        const ns = { namespace: 'tools:abc' };
        const frames: ExecStepEventData[] = [
            // first frame without timestamp: startedAt comes from the next frame
            { call_id: 'th1', task_id: 't', name: 'thinking', step_type: 'thinking', status: 'end', output: 'a ' },
            { call_id: 'th1', task_id: 't', name: 'thinking', step_type: 'thinking', status: 'end', output: 'a ', timestamp: 3 },
            { call_id: 'th1', task_id: 't', name: 'thinking', step_type: 'thinking', status: 'end', output: 'b', timestamp: 4 },
            // parallel tools: start A, start B, end A, end B
            { call_id: 'A', task_id: 't', name: 'read_file', step_type: 'tool', status: 'start', params: { p: 1 }, output: '', timestamp: 5, extra_info: { x: 1 } },
            { call_id: 'B', task_id: 't', name: 'execute', step_type: 'tool', status: 'start', params: {}, timestamp: 5 },
            { call_id: 'A', task_id: 't', name: 'read_file', step_type: 'tool', status: 'end', params: {}, output: 'okA', timestamp: 6, extra_info: { y: 2 } },
            { call_id: 'B', task_id: 't', name: 'execute', step_type: 'tool', status: 'end', params: { code: 'c' }, output: 'okB', timestamp: 8 },
            // dropped frames sharing a call_id with nothing renderable
            { call_id: 'Q', task_id: 't', name: 'ask_user', step_type: 'tool', status: 'start', timestamp: 9 },
            { call_id: 'L', task_id: 't', name: 'ls', step_type: 'tool', status: 'end', timestamp: 9 },
            // answered clarify (no call_id) is a segment boundary
            { step_type: 'call_user_input', task_id: 't', is_completed: true, timestamp: 10 },
            { call_id: 'wt', task_id: 't', name: 'write_todos', step_type: 'tool', status: 'start', timestamp: 11 },
            { call_id: 'wt', task_id: 't', name: 'write_todos', step_type: 'tool', status: 'end', timestamp: 11 },
            // delegation + subagent-internal steps
            { call_id: 'task1', task_id: 't', name: 'general-purpose', step_type: 'subagent', status: 'start', call_reason: 'goal', timestamp: 12 },
            { call_id: 'sth', task_id: 't', name: 'thinking', step_type: 'thinking', status: 'end', output: 'sub ', extra_info: ns, timestamp: 12 },
            { call_id: 'sth', task_id: 't', name: 'thinking', step_type: 'thinking', status: 'end', output: 'think', extra_info: ns, timestamp: 13 },
            { call_id: 'stool', task_id: 't', name: 'web_search', step_type: 'tool', status: 'start', extra_info: ns, timestamp: 13 },
            { call_id: 'task1', task_id: 't', name: 'general-purpose', step_type: 'subagent', status: 'end', output: 'done', timestamp: 15 },
            // a tool left running (start only) at the tail
            { call_id: 'C', task_id: 't', name: 'execute', step_type: 'tool', status: 'start', params: { code: 'x' }, timestamp: 16 },
        ];
        expectEquivalentOnEveryPrefix(frames);
        expect(fold(frames).filter((f) => f.call_id === 'th1')).toHaveLength(1);
    });

    it('never mutates the input history', () => {
        const first: ExecStepEventData = { call_id: 'x', step_type: 'thinking', name: 'thinking', status: 'end', output: 'a' };
        const history = Object.freeze([Object.freeze(first)]) as ExecStepEventData[];
        const next = appendStepFrame(history, { ...first, output: 'b' });
        expect(next).not.toBe(history);
        expect(history[0].output).toBe('a');
        expect(next[0].output).toBe('ab');
    });

    it('a persisted (already folded) history passes through unchanged', () => {
        const history = persisted as ExecStepEventData[];
        expect(comparable(mergeStepFrames(fold(history)))).toEqual(comparable(mergeStepFrames(history)));
    });
});
