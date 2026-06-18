/**
 * F035 Track H (P3): subagent delegation row + per-agent cards (spec §3,
 * step_type=subagent). Header: "auto-delegated N <name> subagents"; expanded:
 * side-by-side small cards. A running card shows the tool currently being
 * called inside that agent's namespace; a finished card shows "called N tools".
 */
import { Outlined } from 'bisheng-icons';
import type { CSSProperties } from 'react';
import { useLocalize } from '~/hooks';
import { StepRow, stepTypeIcon } from './StepRow';
import type { SubagentGroup } from './stepUtils';

/** Dotted base texture, reused verbatim from the clarification card
 *  (ClarifyCard): a 5px-tiled SVG with a faint #EAEEFF dot. */
const DOT_BG: CSSProperties = {
    backgroundColor: '#FFFFFF',
    backgroundImage:
        'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'5\' height=\'5\'%3E%3Ccircle cx=\'0.5\' cy=\'0.5\' r=\'0.5\' fill=\'%23EAEEFF\'/%3E%3C/svg%3E")',
    backgroundSize: '5px 5px',
};
/** Diagonal glint overlaid on the dotted base (Figma 12221:40064). A soft grey
 *  streak on its own layer; the `animate-sheen-sweep` keyframe slides it across
 *  the card (clipped by the card's overflow-hidden) so the gradient flows. A
 *  plain white streak is invisible on the near-white card, so it carries a light
 *  grey cast to read as motion. */
const SHEEN =
    'linear-gradient(120deg, transparent 0%, rgba(140,140,140,0.025) 28%, rgba(140,140,140,0.09) 50%, rgba(140,140,140,0.025) 72%, transparent 100%)';

function SubagentCard({ agent }: { agent: SubagentGroup['agents'][number] }) {
    const localize = useLocalize();
    const { step, children } = agent;
    // count only finished tool-ish child steps for the "called N tools" summary
    const calledCount = children.length;
    const currentTool = [...children].reverse().find((c) => c.running) || children[children.length - 1];

    // the dotted texture stays in both states; the sweeping sheen is the
    // "in-progress" treatment only and stops once the agent finishes.
    const running = step.running;

    return (
        <div
            className="relative flex min-w-40 max-w-56 flex-col items-start gap-1 overflow-hidden rounded-lg border-[0.5px] border-[#ECECEC] px-4 py-2 shadow-[0px_4px_6px_0px_rgba(167,186,224,0.05)]"
            style={DOT_BG}
        >
            {/* diagonal glint sweeping above the dots; semi-transparent so the
                dot texture still reads through. The static mask fades the streak
                near the card's L/R edges, so the overflow-hidden clip lands in an
                already-transparent zone instead of cutting the band into a hard
                vertical line. Only while the agent is running. */}
            {running && (
                <div
                    aria-hidden
                    className="pointer-events-none absolute inset-0"
                    style={{
                        WebkitMaskImage: 'linear-gradient(to right, transparent 0%, #000 18%, #000 82%, transparent 100%)',
                        maskImage: 'linear-gradient(to right, transparent 0%, #000 18%, #000 82%, transparent 100%)',
                    }}
                >
                    <div className="absolute inset-0 animate-sheen-sweep" style={{ backgroundImage: SHEEN }} />
                </div>
            )}
            {/* circular white badge carrying the agent's type icon */}
            <span className="relative flex items-center rounded-full bg-white p-[5px]">
                {stepTypeIcon(step.name, 14)}
            </span>
            <span className="relative max-w-full truncate text-xs leading-5 text-[#1D2129]">{step.name}</span>
            <div className="relative flex max-w-full items-center gap-2 text-xs leading-5 text-[#999]">
                {step.running ? (
                    <>
                        <span className="size-2 shrink-0 animate-pulse-scale rounded-full bg-black" />
                        <span className="truncate">{currentTool?.name || localize('com_linsight_subagent_running')}</span>
                    </>
                ) : (
                    <>
                        <Outlined.DoubleCheck size={12} className="shrink-0 text-[#333]" />
                        <span className="truncate">
                            {localize('com_linsight_subagent_tools_called', { 0: String(calledCount) })}
                        </span>
                    </>
                )}
            </div>
        </div>
    );
}

export function SubagentRow({ group }: { group: SubagentGroup }) {
    const localize = useLocalize();
    const running = group.agents.some((a) => a.step.running);
    // first agent's call_reason doubles as the capability hint in parentheses
    const reason = group.agents[0]?.step.callReason;

    return (
        <StepRow
            icon={<Outlined.PeopleRound size={16} className="text-[#333]" />}
            title={
                <span>
                    {localize('com_linsight_subagent_delegate', {
                        0: String(group.agents.length),
                        1: group.name,
                    })}
                    {reason && <span className="text-gray-400">（{reason}）</span>}
                </span>
            }
            running={running}
        >
            <div className="flex flex-wrap gap-2 py-1">
                {group.agents.map((agent) => (
                    <SubagentCard key={agent.step.callId} agent={agent} />
                ))}
            </div>
        </StepRow>
    );
}
