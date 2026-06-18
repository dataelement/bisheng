/**
 * SubagentTeamGroup + SubagentTrack render tests (Wave3 — full-width drilldown +
 * polished card grid). Additive: the existing stepUtils.test.ts (20 cases) is
 * untouched and stays green.
 *
 * Covers:
 *  (a) collapsed grid renders N polished cards (dot texture + circular badge);
 *  (b) clicking a card toggles it open, drilldown DeepStepGroup/ToolRowLite
 *      appears, and the track root spans the full row (gridColumn '1 / -1');
 *  (c) multiple cards can be expanded independently (no single-select);
 *  (d) a running card renders the sheen layer + pulse dot; a done card renders
 *      the green Check + summary and NO sheen;
 *  (e) collapse state persists across remount (sessionStorage via useCollapseState).
 */
import { fireEvent, render, screen, within } from '@testing-library/react';
import { RecoilRoot } from 'recoil';
import SubagentTeamGroup from './SubagentTeamGroup';
import { mergeStepFrames } from './stepUtils';
import type { ExecStepEventData, SubagentAgent, SubagentGroup } from './stepUtils';

// Localize → echo the key with {{n}} interpolated, so assertions stay readable
// without booting i18next inside jsdom.
jest.mock('~/hooks', () => ({
    useLocalize: () => (key: string, opts?: Record<string, unknown>) => {
        if (!opts) return key;
        return Object.entries(opts).reduce(
            (acc, [k, v]) => acc.replace(new RegExp(`\\{\\{${k}\\}\\}`, 'g'), String(v)),
            key,
        );
    },
}));

function frame(over: Partial<ExecStepEventData>): ExecStepEventData {
    return { task_id: 't1', status: 'end', params: {}, output: null, extra_info: {}, ...over };
}

/**
 * Build a SubagentAgent the way buildFlowNodes does: `agent.step` is the FIRST
 * namespaced INTERNAL step (NOT the main-graph subagent delegation frame, which
 * buildFlowNodes consumes separately), and `agent.children` are later same-ns
 * internal steps. None carries a delegation frame, so drilling
 * buildTimelineGroups over [step, ...children] collapses to deep_step_groups
 * (the L3 drilldown contract). `goal` rides on the anchor's call_reason so the
 * card title renders it.
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

/** A 3-subagent done group (the realistic 22→3 shape). */
function doneGroup(): SubagentGroup {
    return {
        kind: 'subagent_group',
        name: 'general-purpose',
        agents: [
            makeAgent('ns-a', 1, '调研框架 A', false, [
                { name: 'web_search', step_type: 'tool', output: 'hit A' },
                { name: 'thinking', step_type: 'thinking', output: 'pondering A' },
            ]),
            makeAgent('ns-b', 2, '调研框架 B', false, [
                { name: 'web_search', step_type: 'tool', output: 'hit B' },
            ]),
            makeAgent('ns-c', 3, '调研框架 C', false, [
                { name: 'web_search', step_type: 'tool', output: 'hit C' },
            ]),
        ],
    };
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

describe('SubagentTeamGroup — collapsed card grid (a)', () => {
    it('renders one polished card per agent with the dot-texture ground', () => {
        renderGroup(doneGroup());
        // Group header is expanded by default for a DONE group? No: default = running
        // (false here). Expand the group first so the cards mount.
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));
        // 3 polished card shells, one per agent (data-persist-key = namespace).
        const cards = document.querySelectorAll('[data-persist-key^="ns-"]');
        expect(cards.length).toBe(3);
        // Each card's header carries its delegation goal as the title (the goal
        // may also echo inside the collapsed drilldown rows, so assert >= 1).
        expect(within(cards[0] as HTMLElement).getAllByText('调研框架 A').length).toBeGreaterThan(0);
        expect(within(cards[1] as HTMLElement).getAllByText('调研框架 B').length).toBeGreaterThan(0);
        expect(within(cards[2] as HTMLElement).getAllByText('调研框架 C').length).toBeGreaterThan(0);
        // Dot-texture ground is applied inline (jsdom drops the data-uri url but
        // keeps the 5px tile size — a stable fingerprint of DOT_BG).
        expect((cards[0] as HTMLElement).style.backgroundSize).toBe('5px 5px');
    });
});

describe('SubagentTrack — full-width drilldown on expand (b)', () => {
    it('toggles open, reveals the real internal trail, and spans the full row', () => {
        renderGroup(doneGroup());
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));

        // The card shell IS the grid item (data-persist-key on the shell div).
        const cardA = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        const header = cardA.querySelector('button') as HTMLButtonElement; // the toggle
        // collapsed: gridColumn not forced to span.
        expect(cardA.style.gridColumn).toBe('');

        fireEvent.click(header);
        // expanded: the card shell spans the whole content column.
        expect(cardA.style.gridColumn).toBe('1 / -1');
        // drilldown surfaced the subagent's REAL internal trail — DeepStepGroup /
        // ToolRowLite render their own collapsible buttons. The header button plus
        // at least one inner trail button = the drilldown is present and FULL WIDTH
        // (it lives inside the now-spanning shell, not the old ~240px column).
        expect(within(cardA).getAllByRole('button').length).toBeGreaterThan(1);
    });
});

describe('SubagentTrack — independent multi-expand (c)', () => {
    it('expands two cards at once (no single-select reset)', () => {
        renderGroup(doneGroup());
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));

        const cardA = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        const cardB = document.querySelector('[data-persist-key="ns-b"]') as HTMLElement;
        fireEvent.click(cardA.querySelector('button') as HTMLButtonElement);
        fireEvent.click(cardB.querySelector('button') as HTMLButtonElement);

        expect(cardA.style.gridColumn).toBe('1 / -1');
        expect(cardB.style.gridColumn).toBe('1 / -1');
    });
});

describe('SubagentTrack — running vs done visuals (d)', () => {
    it('running card renders the sheen layer + pulse dot; done card renders Check + summary, no sheen', () => {
        const group: SubagentGroup = {
            kind: 'subagent_group',
            name: 'general-purpose',
            agents: [
                makeAgent('ns-run', 1, '运行中的子代理', true, [
                    { name: 'web_search', step_type: 'tool', output: '搜索中' },
                ]),
                makeAgent('ns-done', 2, '已完成的子代理', false, [
                    { name: 'web_search', step_type: 'tool', output: 'ok' },
                ]),
            ],
        };
        renderGroup(group);
        // group is running → expanded by default, cards already mounted.
        const runCard = document.querySelector('[data-persist-key="ns-run"]') as HTMLElement;
        const doneCard = document.querySelector('[data-persist-key="ns-done"]') as HTMLElement;

        // sheen layer = animate-sheen-sweep, only on the running card.
        expect(runCard.querySelector('.animate-sheen-sweep')).not.toBeNull();
        expect(doneCard.querySelector('.animate-sheen-sweep')).toBeNull();
        // running pulse dot present on the running card.
        expect(runCard.querySelector('.animate-pulse')).not.toBeNull();
        // done summary uses the localized key with counts (1 tool · 0 thoughts).
        expect(within(doneCard).getByText(/com_linsight_subagent_summary/)).toBeInTheDocument();
    });
});

describe('SubagentTrack — collapse persistence across remount (e)', () => {
    it('a manual expand survives a fresh RecoilRoot mount (sessionStorage)', () => {
        const group = doneGroup();
        const first = renderGroup(group);
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));
        const cardA = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        fireEvent.click(cardA.querySelector('button') as HTMLButtonElement);
        expect(cardA.style.gridColumn).toBe('1 / -1');
        first.unmount();

        // Fresh mount: the team group default-collapses (done), expand it, then the
        // track must restore its persisted open state from sessionStorage.
        renderGroup(group);
        fireEvent.click(screen.getByText(/com_linsight_subagent_team_done/));
        const cardA2 = document.querySelector('[data-persist-key="ns-a"]') as HTMLElement;
        expect(cardA2.style.gridColumn).toBe('1 / -1');
    });
});
