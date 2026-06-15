/**
 * F035 Track H (P3): subagent delegation row + per-agent cards (spec §3,
 * step_type=subagent). Header: "auto-delegated N <name> subagents"; expanded:
 * side-by-side small cards. A running card shows the tool currently being
 * called inside that agent's namespace; a finished card shows "called N tools".
 */
import { Outlined } from 'bisheng-icons';
import { Check, Recycle } from 'lucide-react';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { StepRow } from './StepRow';
import type { MergedStep, SubagentGroup } from './stepUtils';

function SubagentCard({ agent }: { agent: SubagentGroup['agents'][number] }) {
    const localize = useLocalize();
    const { step, children } = agent;
    // count only finished tool-ish child steps for the "called N tools" summary
    const calledCount = children.length;
    const currentTool = [...children].reverse().find((c) => c.running) || children[children.length - 1];

    return (
        <div className="min-w-40 max-w-56 rounded-xl border border-gray-200 bg-white p-2.5 shadow-sm">
            <div className="flex items-center gap-1.5 text-xs font-medium text-gray-700">
                <Recycle size={12} className="shrink-0 text-blue-500" />
                <span className="truncate">{step.name}</span>
            </div>
            <div className="mt-1.5 flex items-center gap-1.5 text-xs text-gray-500">
                {step.running ? (
                    <>
                        <span className="size-1.5 shrink-0 animate-pulse rounded-full bg-blue-500" />
                        <span className="truncate">{currentTool?.name || localize('com_linsight_subagent_running')}</span>
                    </>
                ) : (
                    <>
                        <Check size={12} className="shrink-0 text-green-500" />
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
            icon={<Outlined.PeopleRound size={14} className={cn(running ? 'text-primary' : 'text-[#333]')} />}
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
