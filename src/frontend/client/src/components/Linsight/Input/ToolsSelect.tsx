/**
 * F035 Track H: tools dropdown of the task-mode input. One row per tool with
 * a toggle switch (spec §1, fig.7 — e.g. web search / TianYanCha / drawing).
 * Tool list source is the same as the legacy LinsiTools: admin-configured
 * bsConfig.linsightConfig.tools. No chips are generated for tools.
 */
import { ChevronDown, Hammer } from 'lucide-react';
import { Switch } from '~/components/ui';
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuTrigger,
} from '~/components/ui';
import { useLocalize } from '~/hooks';
import type { TaskModeToolItem } from '~/store/linsight';
import { cn } from '~/utils';

interface ToolsSelectProps {
    tools: TaskModeToolItem[];
    disabled?: boolean;
    onChange: (tools: TaskModeToolItem[]) => void;
}

export function ToolsSelect({ tools, disabled = false, onChange }: ToolsSelectProps) {
    const localize = useLocalize();
    const active = tools.some((tool) => tool.checked);

    if (tools.length === 0) return null;

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild disabled={disabled}>
                <button
                    type="button"
                    className={cn(
                        'flex h-7 shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2 text-xs font-normal outline-none transition-colors hover:bg-black/5',
                        active ? 'text-blue-600' : 'text-[#4E5969]',
                        disabled && 'cursor-not-allowed opacity-50',
                    )}
                >
                    <Hammer size={16} />
                    <span className="truncate max-w-[min(30vw,120px)]">{localize('com_tools_title')}</span>
                    <ChevronDown size={14} className="text-slate-400" />
                </button>
            </DropdownMenuTrigger>

            <DropdownMenuContent
                align="start"
                className="flex max-h-[320px] w-64 flex-col gap-0 overflow-y-auto rounded-2xl border-slate-100 p-2 shadow-xl"
            >
                {tools.map((tool) => (
                    <div key={String(tool.id)} className="flex items-center justify-between gap-2 rounded-lg px-1.5 py-2">
                        <div className="flex min-w-0 items-center gap-2">
                            <Hammer size={16} className="shrink-0 text-slate-600" />
                            <span className="line-clamp-1 max-w-40 text-xs font-normal text-slate-700">
                                {tool.name}
                            </span>
                        </div>
                        <Switch
                            className="data-[state=checked]:bg-blue-600"
                            disabled={disabled}
                            checked={tool.checked}
                            onCheckedChange={(checked) =>
                                onChange(tools.map((t) => (t.id === tool.id ? { ...t, checked } : t)))
                            }
                        />
                    </div>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
