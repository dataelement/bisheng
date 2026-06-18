/**
 * SubagentTeamGroup + SubagentTrack render tests (monitor-panel rebuild, §2.2/§2.3).
 * Additive: the existing stepUtils.test.ts is untouched and stays green.
 *
 * Covers:
 *  (a) the team header reads the stable "已派出 N 个子智能体调研（用时 M 秒）" label
 *      (count interpolated), and the monitor panel renders one row per agent
 *      (data-persist-key = namespace);
 *  (b) clicking a row toggles its drilldown open — the real internal trail
 *      (DeepStepGroup / ToolRowLite) is revealed (grid 0fr→1fr). The drilldown is
 *      kept MOUNTED behind the grid collapse (the §2.1 animation contract), so we
 *      assert on the open/closed grid state, not on whether inner nodes exist;
 *  (c) multiple rows can be expanded independently (no single-select);
 *  (d) a running row renders the Loading spinner; a done row has no spinner and
 *      carries NO activity meta (stable scheme — title + optional elapsed only);
 *  (e) collapse state persists across remount (sessionStorage via useCollapseState).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { RecoilRoot } from 'recoil';
import SubagentTeamGroup from './SubagentTeamGroup';
import { mergeStepFrames } from './stepUtils';
import type { ExecStepEventData, SubagentAgent, SubagentGroup } from './stepUtils';

// Localize → echo the key, then surface the interpolated option values, so
// assertions stay readable without booting i18next inside jsdom. The real keys
// (e.g. "已派出 {{0}} 个子智能体并行调研") carry positional {{0}} placeholders that
// the component fills via `localize(key, { 0: count })`; the test never sees the
// translated phrase, so we keep the KEY (proves WHICH phrase rendered) AND append
// the option values (proves the count was wired through) — e.g.
// "com_linsight_subagent_team_done 3".
jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string, opts?: Record<string, unknown>) => {
        if (!opts) return key;
        const values = Object.values(opts).map((v) => String(v));
        return values.length ? `${key} ${values.join(' ')}` : key;
    },
}));

function frame(over: Partial<ExecStepEventData>): ExecStepEventData {
    return { task_id: 't1', status: 'end', params: {}, output: null, extra_info: {}, ...over };
}

/**
 * Build a SubagentAgent the way buildFlowNodes does: `agent.step` is the FIRST
 * namespaced INTERNAL step and `agent.children` are later same-ns internal steps.
 * None carries a delegation frame, so drilling buildTimelineGroups over the
 * children collapses to deep_step_groups (the L3 drilldown contract). `goal`
 * rides on the anchor's call_reason so the card title renders it.
 */
function makeAgent(
    ns: string,
    idx: number,
    goal: string,
    running: boolean,
    internal: Partial<ExecStepEventData>[],
): SubagentAgent {
    const frames = internal.map((c, i) =>
        frame({
            call_id: `${ns}_s${i}`,
            ...c,
            call_reason: i === 0 ? goal : c.call_reason,
            status: running && i === internal.length - 1 ? 'start' : 'end',
            extra_info: { ...(c.extra_info || {}), namespace: ns },
        }),
    );
    const [step, ...children] = mergeStepFrames(frames);
    return { step, children, idx };
}

/** A 3-subagent done group (the realistic 22→3 shape). Each agent has an anchor
 *  step plus child tool steps so the activity meta has something to summarize. */
function doneGroup(): SubagentGroup {
    return {
        kind: 'subagent_group',
        name: 'general-purpose',
        agents: [
            makeAgent('ns-a', 1, '调研框架 A', false, [
                { name: 'thinking', step_type: 'thinking', output: 'pondering A' },
                { name: 'web_search', step_type: 'tool', output: 'hit A' },
            ]),
            makeAgent('ns-b', 2, '调研框架 B', false, [
                { name: 'thinking', step_type: 'thinking', output: 'pondering B' },
                { name: 'web_search', step_type: 'tool', output: 'hit B' },
            ]),
            makeAgent('ns-c', 3, '调研框架 C', false, [
                { name: 'thinking', step_type: 'thinking', output: 'pondering C' },
                { name: 'web_search', step_type: 'tool', output: 'hit C' },
            ]),
        ],
    };
}

/**
 * Read whether a SubagentTrack row's drilldown is OPEN. The drilldown is kept
 * mounted behind a grid 0fr↔1fr collapse (§2.1 animation contract), so "open"
 * is the row's drilldown grid showing `gridTemplateRows: 1fr` — NOT the mere
 * presence of inner buttons (which exist even when collapsed). The drilldown is
 * the row's grid sibling of the header toggle button.
 */
function isRowOpen(row: HTMLElement): boolean {
    const grid = Array.from(row.querySelectorAll<HTMLElement>(':scope > div')).find(
        (el) => el.style.gridTemplateRows === '1fr' || el.style.gridTemplateRows === '0fr',
    );
    return grid?.style.gridTemplateRows === '1fr';
}

function renderGroup(group: SubagentGroup) {
    return render(
        <RecoilRoot>
            <SubagentTeamGroup group={group} />
        </RecoilRoot>,
    );
}

beforeEach(() => {
    try {
        sessionStorage.clear();
    } catch {
        /* ignore */
    }
});

describe('SubagentTeamGroup — monitor panel header + rows (a)', () => {
    it('renders the parallel title and one panel row per agent', () => {
        renderGroup(doneGroup());
        // Header title = "已派出 N 个子智能体并行调研" (count interpolated). A done group
        // default-collapses, so expand it first to mount the rows.
        const header = screen.getByText(/com_linsight_subagent_team_done/);
        expect(header.textContent).toContain('3');
        fireEvent.click(header);

        // 3 panel rows, one per agent (data-persist-key = namespace).
        const rows = document.querySelectorAll('[data-persist-key^="ns-"]');
        expect(rows.length).toBe(3);
        // Each row's header carries its delegation goal as the hero title.
        expect(within(rows[0] as HTMLElement).getAllByText('调研框架 A').length).toBeGreaterThan(0);
        expect(within(rows[1] as HTMLElement).getAllByText('调研框架 B').length).toBeGreaterThan(0);
        expect(within(rows[2] as HTMLElement).getAllByText('调研框架 C').length).toBeGreaterThan(0);
    });
});

describe('SubagentTrack — drilldown on expand (b)', () => {
    it('toggles open and reveals the real internal trail', () => {
        renderGroup(doneGroup());
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));

        const rowA = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        const header = rowA.querySelector('button') as HTMLButtonElement; // the toggle
        // collapsed by default (L3): the drilldown grid is folded to 0fr.
        expect(isRowOpen(rowA)).toBe(false);
        // the real internal trail is mounted behind the collapse — DeepStepGroup /
        // ToolRowLite render their own buttons even while folded.
        expect(within(rowA).getAllByRole('button').length).toBeGreaterThan(1);

        fireEvent.click(header);
        // expanded: the drilldown grid opens to 1fr, revealing the internal trail.
        expect(isRowOpen(rowA)).toBe(true);
    });
});

describe('SubagentTrack — independent multi-expand (c)', () => {
    it('expands two rows at once (no single-select reset)', () => {
        renderGroup(doneGroup());
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));

        const rowA = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        const rowB = document.querySelector('[data-persist-key="ns-b"]') as HTMLElement;
        fireEvent.click(rowA.querySelector('button') as HTMLButtonElement);
        fireEvent.click(rowB.querySelector('button') as HTMLButtonElement);

        // Both drilldowns are open at once (no single-select reset).
        expect(isRowOpen(rowA)).toBe(true);
        expect(isRowOpen(rowB)).toBe(true);
    });
});

describe('SubagentTrack — running vs done status (d)', () => {
    it('running row renders the Loading spinner; done row has no spinner and no activity meta (stable scheme)', () => {
        const group: SubagentGroup = {
            kind: 'subagent_group',
            name: 'general-purpose',
            agents: [
                makeAgent('ns-run', 1, '运行中的子代理', true, [
                    { name: 'web_search', step_type: 'tool', output: '锚点' },
                    { name: 'web_search', step_type: 'tool', output: '搜索中' },
                ]),
                makeAgent('ns-done', 2, '已完成的子代理', false, [
                    { name: 'web_search', step_type: 'tool', output: '锚点' },
                    { name: 'web_search', step_type: 'tool', output: 'ok' },
                ]),
            ],
        };
        renderGroup(group);
        // group is running → expanded by default, rows already mounted.
        const runRow = document.querySelector('[data-persist-key="ns-run"]') as HTMLElement;
        const doneRow = document.querySelector('[data-persist-key="ns-done"]') as HTMLElement;

        // running row → Loading spinner (animate-spin); done row has none.
        expect(runRow.querySelector('.animate-spin')).not.toBeNull();
        expect(doneRow.querySelector('.animate-spin')).toBeNull();
        // Stable scheme (reverted): the card header carries NO activity meta — not
        // the readable "联网搜索 N 次" clause, nor the old "N 个工具 · N 思考" jargon.
        // The title (delegation goal) and an optional elapsed clause are all that
        // remain. Assert across the whole row so a mounted-collapsed drilldown
        // can't sneak an activity key past a header-scoped query.
        expect(within(doneRow).queryByText(/com_linsight_act_/)).toBeNull();
        expect(within(doneRow).queryByText(/com_linsight_subagent_summary/)).toBeNull();
        // The delegation goal still renders as the card title.
        expect(within(doneRow).getAllByText('已完成的子代理').length).toBeGreaterThan(0);
    });
});

describe('SubagentTrack — collapse persistence across remount (e)', () => {
    it('a manual expand survives a fresh RecoilRoot mount (sessionStorage)', () => {
        const group = doneGroup();
        const first = renderGroup(group);
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));
        const rowA = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        fireEvent.click(rowA.querySelector('button') as HTMLButtonElement);
        expect(isRowOpen(rowA)).toBe(true);
        first.unmount();

        // Fresh mount: the team group default-collapses (done), expand it, then the
        // row must restore its persisted open drilldown from sessionStorage.
        renderGroup(group);
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));
        const rowA2 = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        expect(isRowOpen(rowA2)).toBe(true);
    });
});
