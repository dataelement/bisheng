/**
 * F035 Track H: tools picker of the task-mode input — a multiple Select, one
 * option per tool (spec §1, fig.7 — e.g. web search / TianYanCha / drawing);
 * the pill itself shows whether any tool is on.
 * Tool list source is the same as the legacy LinsiTools: admin-configured
 * bsConfig.linsightConfig.tools. No chips are generated for tools.
 */
import { ChevronDown, Hammer } from 'lucide-react';
import { Select } from '@bisheng/ui';
import { useLocalize } from '~/hooks';
import useSelectCopy from '~/hooks/useSelectCopy';
import type { TaskModeToolItem } from '~/store/linsight';
import { cn } from '~/utils';

interface ToolsSelectProps {
    tools: TaskModeToolItem[];
    disabled?: boolean;
    onChange: (tools: TaskModeToolItem[]) => void;
    /** Toolbar out of room (see useContainerCompact): collapse label to icon. */
    compact?: boolean;
}

export function ToolsSelect({ tools, disabled = false, onChange, compact = false }: ToolsSelectProps) {
    const localize = useLocalize();
    const selectCopy = useSelectCopy();
    const active = tools.some((tool) => tool.checked);

    if (tools.length === 0) return null;

    return (
        <Select
            {...selectCopy}
            multiple
            disabled={disabled}
            options={tools.map((tool) => ({
                value: String(tool.id),
                label: tool.name,
                icon: <Hammer />,
            }))}
            value={tools.filter((tool) => tool.checked).map((tool) => String(tool.id))}
            onChange={(next) =>
                onChange(tools.map((tool) => ({ ...tool, checked: next.includes(String(tool.id)) })))
            }
            aria-label={localize('com_tools_title')}
            trigger={
                <button
                    type="button"
                    disabled={disabled}
                    aria-label={localize('com_tools_title')}
                    className={cn(
                        'flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-xs font-normal outline-none transition-colors hover:bg-black/5',
                        // Active highlight uses brand-600 to match the checked-checkbox
                        // color in the picker dropdowns (KnowledgeSpaceSelect rows).
                        active ? 'text-blue-600' : 'text-text-2',
                        disabled && 'cursor-not-allowed opacity-50',
                    )}
                >
                    <Hammer size={16} />
                    {!compact && <span className="truncate">{localize('com_tools_title')}</span>}
                    <ChevronDown size={14} className="text-slate-400" />
                </button>
            }
        />
    );
}
