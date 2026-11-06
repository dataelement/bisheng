import type { ReactNode } from 'react';
import { DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '~/components/ui';
import { cn } from '~/utils';

/** Same viewport margin the "+" menu itself keeps (ChatKnowledge BOTTOM_GAP). */
const COLLISION_PADDING = 8;

interface PlusMenuSubProps {
  icon: ReactNode;
  label: string;
  /** Width / max-height / gap of the side panel; the shell (radius, shadow, padding) is fixed. */
  panelClassName?: string;
  /** Controlled open state — omit to let the menu manage it. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: ReactNode;
}

/**
 * Desktop row of the chat input's "+" menu that opens a side panel on hover
 * (知识空间 / 组织知识库 / 工具 / 添加技能). The panel centers vertically on its row
 * rather than aligning top edges, so tall lists stay near the pointer.
 */
export function PlusMenuSub({ icon, label, panelClassName, open, onOpenChange, children }: PlusMenuSubProps) {
  return (
    <DropdownMenuSub open={open} onOpenChange={onOpenChange}>
      <DropdownMenuSubTrigger className="flex h-8 cursor-pointer items-center justify-between rounded-lg px-2 outline-none">
        <div className="flex min-w-0 items-center gap-2">
          {/* Keeps its 16px when a long label truncates. */}
          <span className="flex shrink-0">{icon}</span>
          <span className="truncate text-[14px] font-normal text-text-1">{label}</span>
        </div>
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent
        align="center"
        collisionPadding={COLLISION_PADDING}
        className={cn(
          'dsh-chat-menu ml-2 flex max-h-[440px] w-[240px] flex-col overflow-hidden rounded-2xl border-0 bg-bg-page px-3 pb-0 pt-3 shadow-[0_2px_16px_-2px_rgba(0,23,66,0.10)]',
          panelClassName,
        )}
      >
        {children}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
