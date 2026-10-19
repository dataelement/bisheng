import { ComposerSubmenu } from './ComposerSubmenu';
import { Outlined } from 'bisheng-icons';
import { SkillSelector } from '~/components/Linsight/Input/SkillSelector';
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '~/components/ui';
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
    if (menu) return <ComposerSubmenu label={localize('com_linsight_add_skill')}
        icon={<Outlined.Skill size={16} />} disabled={disabled}>
        <SkillSelector selected={selected} onChange={onChange} layout="command" />
    </ComposerSubmenu>;
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
