/** @jest-environment node */
import { renderToStaticMarkup } from 'react-dom/server';
import { ExecutionTimeline } from './ExecutionTimeline';
import { ExecutionLiveContext } from './executionLive';
import type { ExecStepEventData } from './execTypes';

let mockMobile = true;
jest.mock('~/hooks/usePrefersMobileLayout', () => ({
    __esModule: true,
    default: () => mockMobile,
}));
jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string, values?: Record<string, string>) =>
        `${key}:${values?.[0] ?? ''}/${values?.[1] ?? ''}`,
}));
jest.mock('~/store/linsightCollapse', () => ({
    // An old saved "expanded" choice must not mount process details on mobile.
    useCollapseState: () => [true, () => {}],
}));
jest.mock('bisheng-icons', () => ({
    Outlined: new Proxy({}, { get: () => () => null }),
}));
jest.mock('~/utils', () => ({
    cn: (...parts: unknown[]) => parts.filter(Boolean).join(' '),
}));

const history: ExecStepEventData[] = [
    { task_id: 't', call_id: 'thinking', step_type: 'thinking', name: 'thinking', status: 'end', output: 'Private reasoning' },
    { task_id: 't', call_id: 'tool', step_type: 'tool', name: 'web_search', status: 'end', output: 'Large tool result' },
    { task_id: 't', call_id: 'agent', step_type: 'subagent', name: 'general-purpose', status: 'start', extra_info: { delegate_goal: 'Delegated research' } },
    { task_id: 't', call_id: 'nested', step_type: 'thinking', name: 'thinking', status: 'end', output: 'Subagent reasoning', extra_info: { namespace: 'tools:research' } },
];

beforeEach(() => { mockMobile = true; });

function renderTimeline(frames: ExecStepEventData[]) {
    return renderToStaticMarkup(
        <ExecutionLiveContext.Provider value={false}>
            <ExecutionTimeline history={frames} />
        </ExecutionLiveContext.Provider>,
    );
}

it('does not mount thinking, tools or subagents on mobile despite saved expanded state', () => {
    expect(renderTimeline(history)).toBe('');
});

it('does not read or format process bodies before the mobile rendering boundary', () => {
    const frame: ExecStepEventData = { task_id: 't', call_id: 'large-tool', step_type: 'tool', name: 'web_search' };
    Object.defineProperty(frame, 'output', {
        get: () => { throw new Error('Mobile must not aggregate process output'); },
    });
    expect(renderTimeline([frame])).toBe('');
});

it('keeps full reasoning and tool output available on desktop', () => {
    mockMobile = false;
    const html = renderTimeline(history);
    expect(html).toContain('Private reasoning');
    // Tool details remain lazy even inside an expanded desktop thinking group.
    expect(html).not.toContain('Large tool result');
    expect(html).toContain('Subagent reasoning');
});

it('keeps preparation progress and unavailable-skill warnings without exposing tool bodies', () => {
    const html = renderTimeline([
        ...history,
        { call_id: 'ingest', name: 'ingest_uploads', status: 'start', extra_info: { ingest_progress: { phase: 'running', done: 1, total: 3 } } },
        { call_id: 'skill', name: 'skill_load_failed', extra_info: { skill_load_failed: { names: ['Selected skill'] } } },
    ]);
    expect(html).toContain('com_linsight_ingest_running:1/3');
    expect(html).toContain('Selected skill');
    expect(html).not.toContain('Private reasoning');
    expect(html).not.toContain('Large tool result');
});
