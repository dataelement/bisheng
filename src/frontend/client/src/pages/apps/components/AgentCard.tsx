import type { AppItem } from '~/@types/app';
import { Button } from '~/components';
import AppAvator from '~/components/Avator';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '~/components/ui';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize, useMediaQuery } from '~/hooks';
import { cn } from '~/utils';
import { Outlined } from 'bisheng-icons';
import { MoreVertical } from 'lucide-react';

interface AgentCardProps {
  agent: AppItem;
  /** Pin is optional — surfaces without a pin concept (e.g. the app square) omit it. */
  isPinned?: boolean;
  onTogglePin?: (agent: AppItem) => void;
  onStartChat: (agent: AppItem) => void;
  onShare: (agent: AppItem) => void;
}

export function AgentCard({
  agent,
  isPinned = false,
  onTogglePin,
  onStartChat,
  onShare,
}: AgentCardProps) {
  const localize = useLocalize();
  const isMobileCard = useMediaQuery('(max-width: 576px)');
  const canHover = useMediaQuery('(hover: hover) and (pointer: fine)');
  const shouldUseHoverActions = !isMobileCard && canHover;
  const shouldUseHoverActionsInMobileCard = isMobileCard && canHover;
  // Only render pin affordances when a toggle handler is supplied.
  const showPin = typeof onTogglePin === 'function';

  // Desktop card actions — rendered once, reused for the hover overlay and the
  // no-hover inline fallback.
  const actionButtons = (
    <>
      {agent.can_share === true ? (
        <Button
          onClick={(e) => {
            e.stopPropagation();
            onShare(agent);
          }}
          variant="outline"
          className="flex-1 min-w-0 justify-center items-center h-full max-h-full rounded-[6px] px-2 py-0 text-[14px] font-normal"
        >
          {localize('com_app_share_app')}
        </Button>
      ) : null}
      <Button
        onClick={(e) => {
          e.stopPropagation();
          onStartChat(agent);
        }}
        className="flex-1 min-w-0 justify-center items-center h-full max-h-full rounded-[6px] px-2 py-0 text-[14px] font-normal"
      >
        {localize('com_app_start_chat')}
      </Button>
    </>
  );

  return (
    <div
      className={cn(
        'group/card relative flex cursor-pointer flex-col overflow-hidden rounded-[12px] border border-solid p-2 transition-all',
        'border-[#ebecf0] border-[0.5px] bg-white fine-pointer:hover:shadow-[0px_2.094px_8.796px_1.047px_rgba(117,145,212,0.12)]',
        'after:pointer-events-none after:absolute after:inset-0 after:rounded-[12px] after:border after:border-[#335CFF] after:opacity-0 after:transition-opacity fine-pointer:group-hover/card:after:opacity-100',
        'bg-[linear-gradient(123.519deg,_rgb(249,251,254)_0%,_rgb(255,255,255)_50%,_rgb(249,251,254)_100%)]',
      )}
      onClick={() => onStartChat(agent)}
    >
      {/* Header Info */}
      <div className="flex items-start justify-between w-full relative z-10 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <AppAvator className="size-[32px] min-w-[20px] shrink-0 rounded-[6px]" url={agent.logo} id={agent.id as any} flowType={String(agent.flow_type)} />
          <p className="font-['PingFang_SC'] font-normal leading-[22px] text-[#212121] text-[14px] truncate">
            {agent.name}
          </p>
        </div>

        {isMobileCard ? (
          (showPin || agent.can_share === true) ? (
            <div
              className={cn(
                "flex items-center gap-1 shrink-0 transition-opacity",
                shouldUseHoverActionsInMobileCard
                  ? "opacity-0 pointer-events-none fine-pointer:group-hover/card:opacity-100 fine-pointer:group-hover/card:pointer-events-auto"
                  : "opacity-100 pointer-events-auto",
              )}
            >
              {showPin && isPinned ? (
                <span
                  className="inline-flex size-6 items-center justify-center rounded-[6px] text-[#5773B4]"
                  aria-label={localize('com_app_unpin_tooltip')}
                >
                  <Outlined.Pin size={16} className="shrink-0" />
                </span>
              ) : null}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex size-6 items-center justify-center rounded-[6px] border border-[#E5E6EB] bg-white text-[#86909C] fine-pointer:hover:bg-[#F7F8FA]"
                    aria-label={localize('com_ui_more')}
                  >
                    <MoreVertical className="size-4" />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-[120px]">
                  {showPin ? (
                    <DropdownMenuItem
                      onClick={(e) => {
                        e.stopPropagation();
                        onTogglePin?.(agent);
                      }}
                    >
                      {isPinned ? localize('com_app_unpin_tooltip') : localize('com_app_pin_tooltip')}
                    </DropdownMenuItem>
                  ) : null}
                  {agent.can_share === true ? (
                    <DropdownMenuItem
                      onClick={(e) => {
                        e.stopPropagation();
                        onShare(agent);
                      }}
                    >
                      {localize('com_app_share_app')}
                    </DropdownMenuItem>
                  ) : null}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ) : null
        ) : showPin ? (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin?.(agent);
                  }}
                  className={cn(
                    'group/pin flex shrink-0 cursor-pointer items-center justify-center rounded-[6px] p-1 transition-colors',
                    'border border-transparent fine-pointer:hover:border-[#E5E6EB] fine-pointer:hover:bg-[#f7f8fa]',
                    isPinned
                      ? 'opacity-100'
                      : shouldUseHoverActions
                        ? 'opacity-0 pointer-events-none fine-pointer:group-hover/card:pointer-events-auto fine-pointer:group-hover/card:opacity-100'
                      : 'opacity-100 pointer-events-auto',
                  )}
                  aria-label={
                    isPinned ? localize('com_app_unpin_tooltip') : localize('com_app_pin_tooltip')
                  }
                >
                  {isPinned ? (
                    <span className="relative inline-flex size-[18px] items-center justify-center">
                      <Outlined.Pin
                        size={18}
                        className="absolute shrink-0 text-[#5773B4] transition-opacity fine-pointer:group-hover/pin:opacity-0"
                      />
                      <Outlined.PinOff
                        size={18}
                        className="pointer-events-none absolute text-[#4E5969] opacity-0 transition-opacity fine-pointer:group-hover/pin:opacity-100"
                      />
                    </span>
                  ) : (
                    <Outlined.Pin size={18} className="shrink-0 text-[#4E5969]" />
                  )}
                </button>
              </TooltipTrigger>
              <TooltipContent>
                {isPinned ? localize('com_app_unpin_tooltip') : localize('com_app_pin_tooltip')}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        ) : null}
      </div>

      {/* Description — fixed 3-line block (h = 3 × leading) so every card keeps a
          uniform height regardless of text length; clamp to 3 lines with ellipsis. */}
      <div className="mt-2 h-[58.5px] overflow-hidden font-['PingFang_SC'] font-normal text-[12px] text-[#a9aeb8] leading-[19.5px] break-words line-clamp-3">
        {agent.description || localize('com_app_no_description_placeholder')}
      </div>

      {isMobileCard ? (
        <div className="mt-auto flex w-full min-w-0 items-center justify-between gap-1">
          <div className="relative min-w-0 flex-1 overflow-hidden">
            <div className="flex items-center gap-1 overflow-hidden whitespace-nowrap">
              {(agent.tags && agent.tags.length > 0 ? agent.tags : [{ name: '精选' }]).map((tag, idx) => (
                <div
                  key={idx}
                  className="shrink-0 rounded-[4px] bg-[#f2f3f5] px-2 py-0.5 text-[12px] font-normal leading-[20px] text-[#4e5969]"
                >
                  {tag.name}
                </div>
              ))}
            </div>
            <div className="pointer-events-none absolute right-0 top-0 h-full w-6 bg-gradient-to-l from-white to-transparent" />
          </div>
          <Button
            onClick={(e) => {
              e.stopPropagation();
              onStartChat(agent);
            }}
            variant="outline"
            className={cn(
              "h-6 shrink-0 rounded-[6px] border border-[#E5E6EB] bg-white px-2 py-0 text-[12px] font-normal leading-[20px] text-[#4E5969] transition-opacity fine-pointer:hover:bg-[#F7F8FA]",
              shouldUseHoverActionsInMobileCard
                ? "opacity-0 pointer-events-none fine-pointer:group-hover/card:opacity-100 fine-pointer:group-hover/card:pointer-events-auto"
                : "opacity-100 pointer-events-auto",
            )}
          >
            {localize('com_app_start_chat')}
          </Button>
        </div>
      ) : (
        <div
          className={cn(
            'w-full min-w-0',
            shouldUseHoverActions
              // Hover surfaces: actions overlay the bottom of the description on
              // hover (faded mask hides the text underneath), so the card height
              // stays at title + description without a reserved button row.
              ? 'absolute inset-x-0 bottom-0 z-20 hidden px-2 pb-2 pt-6 [background:linear-gradient(to_top,#ffffff_55%,rgba(255,255,255,0))] fine-pointer:group-hover/card:block'
              // No-hover surfaces: actions sit in normal flow below the description.
              : 'mt-2 block',
          )}
        >
          <div className="flex h-[28px] w-full min-w-0 items-stretch justify-center gap-2">
            {actionButtons}
          </div>
        </div>
      )}
    </div>
  );
}