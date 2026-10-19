import { useState } from 'react';
import { Outlined } from 'bisheng-icons';
import { SkillSelector } from '~/components/Linsight/Input/SkillSelector';
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger, DropdownMenuItem } from '~/components/ui';
import { useLocalize } from '~/hooks';
import type { TaskModeSkill } from '~/store/linsight';

interface Props {
    selected: TaskModeSkill[];
    disabled: boolean;
    menu?: boolean;
    onChange: (skills: TaskModeSkill[]) => void;
}

/** Skill selection shares the existing enterprise list and multi-select state. */
export function ChatSkillSelector({ selected, disabled, onChange, menu }: Props) {
    const localize = useLocalize();
    const [expanded, setExpanded] = useState(false);
    if (menu) return <>
        <DropdownMenuItem disabled={disabled} aria-expanded={expanded}
            onSelect={(event) => { event.preventDefault(); setExpanded((current) => !current); }} className="gap-2">
            <Outlined.Skill size={16} />{localize('com_linsight_add_skill')}
            <Outlined.Down size={14} className="ml-auto" style={{ transform: expanded ? 'rotate(180deg)' : undefined }} />
        </DropdownMenuItem>
        {expanded && <div className="dsh-command-skills">
            <SkillSelector selected={selected} onChange={onChange} />
        </div>}
    </>;
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="ghost"
                    disabled={disabled}
                    className="dsh-composer-control gap-1.5 text-text-2"
                    data-active={selected.length > 0}
                >
                    <Outlined.Skill size={16} />
                    <span>{localize('com_linsight_add_skill')}</span>
                    {selected.length > 0 && <span>{selected.length}</span>}
                    <Outlined.Down size={14} />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent
                align="start"
                side="top"
                sideOffset={8}
                collisionPadding={12}
                className="dsh-chat-menu flex max-h-[min(440px,var(--radix-dropdown-menu-content-available-height))] w-[280px] max-w-[calc(100vw-24px)] flex-col overflow-hidden px-3 pb-0 pt-3"
            >
                <SkillSelector selected={selected} onChange={onChange} />
            </DropdownMenuContent>
        </DropdownMenu>
    );
}
