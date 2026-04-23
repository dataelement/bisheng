import type { AppItem } from '~/@types/app';
import { Button } from '~/components';
import AppAvator from '~/components/Avator';
import { ChannelPinGrayIcon, ChannelPinIcon, ChannelUnpinGrayIcon } from '~/components/icons/channels';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '~/components/ui';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { useLocalize, useMediaQuery } from '~/hooks';
import { cn } from '~/utils';
import { MoreVertical } from 'lucide-react';

interface AgentCardProps {
  agent: AppItem;
  isPinned: boolean;
  onTogglePin: (agent: AppItem) => void;
  onStartChat: (agent: AppItem) => void;
  onShare: (agent: AppItem) => void;
}

export function AgentCard({
  agent,
  isPinned,
  onTogglePin,
  onStartChat,
  onShare,
}: AgentCardProps) {
  const localize = useLocalize();
  const isMobileCard = useMediaQuery('(max-width: 576px)');
  return (
    <div
      className={cn(
        'group/card relative flex h-[132px] cursor-pointer flex-col justify-between overflow-hidden rounded-[6px] border border-solid p-2 transition-all',
        'border-[#ebecf0] border-[0.5px] bg-white hover:shadow-[0px_2.094px_8.796px_1.047px_rgba(117,145,212,0.12)]',
        'after:pointer-events-none after:absolute after:inset-0 after:rounded-[6px] after:border after:border-[#335CFF] after:opacity-0 after:transition-opacity group-hover/card:after:opacity-100',
        'bg-[linear-gradient(123.519deg,_rgb(249,251,254)_0%,_rgb(255,255,255)_50%,_rgb(249,251,254)_100%)]',
      )}
      onClick={() => onStartChat(agent)}
    >
      {/* Header Info */}
      <div className="flex items-start justify-between w-full relative z-10 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <AppAvator className="size-[32px] min-w-[20px] shrink-0 rounded-[4px]" url={agent.logo} id={agent.id as any} flowType={String(agent.flow_type)} />
          <p className="font-['PingFang_SC'] font-normal leading-[22px] text-[#212121] text-[14px] truncate">
            {agent.name}
          </p>
        </div>

        {isMobileCard ? (
          <div className="flex items-center gap-1 shrink-0">
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onTogglePin(agent);
              }}
              className="inline-flex size-6 items-center justify-center rounded-[6px] text-[#86909C] hover:bg-[#F2F3F5]"
              aria-label={
                isPinned ? localize('com_app_unpin_tooltip') : localize('com_app_pin_tooltip')
              }
            >
              {isPinned ? (
                <ChannelPinIcon className="size-[16px] shrink-0" />
              ) : (
                <ChannelPinGrayIcon className="size-[16px] shrink-0" />
              )}
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex size-6 items-center justify-center rounded-[6px] border border-[#E5E6EB] bg-white text-[#86909C] hover:bg-[#F7F8FA]"
                  aria-label={localize('com_ui_more')}
                >
                  <MoreVertical className="size-4" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-[120px]">
                <DropdownMenuItem
                  onClick={(e) => {
                    e.stopPropagation();
                    onShare(agent);
                  }}
                >
                  {localize('com_app_share_app')}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        ) : (
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin(agent);
                  }}
                  className={cn(
                    'group/pin flex shrink-0 cursor-pointer items-center justify-center rounded-[6px] p-1 transition-colors',
                    'border border-transparent hover:border-[#E5E6EB] hover:bg-[#f7f8fa]',
                    isPinned
                      ? 'opacity-100'
                      : 'opacity-0 pointer-events-none group-hover/card:pointer-events-auto group-hover/card:opacity-100 coarse-pointer:opacity-100 coarse-pointer:pointer-events-auto',
                  )}
                  aria-label={
                    isPinned ? localize('com_app_unpin_tooltip') : localize('com_app_pin_tooltip')
                  }
                >
                  {isPinned ? (
                    <span className="relative inline-flex size-[18px] items-center justify-center">
                      <ChannelPinIcon className="absolute size-[18px] shrink-0 transition-opacity group-hover/pin:opacity-0" />
                      <ChannelUnpinGrayIcon className="pointer-events-none absolute size-[18px] opacity-0 transition-opacity group-hover/pin:opacity-100" />
                    </span>
                  ) : (
                    <ChannelPinGrayIcon className="size-[18px] shrink-0" />
                  )}
                </button>
              </TooltipTrigger>
              <TooltipContent>
                {isPinned ? localize('com_app_unpin_tooltip') : localize('com_app_pin_tooltip')}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </div>

      {/* Description */}
      <div className="flex-1 font-['PingFang_SC'] font-normal text-[12px] text-[#a9aeb8] leading-[19.5px] overflow-hidden whitespace-normal break-words line-clamp-2 mt-2 mb-2">
        {agent.description || '暂无描述内容...'}
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
            className="h-6 shrink-0 rounded-[6px] border border-[#E5E6EB] bg-white px-2 py-0 text-[12px] font-normal leading-[20px] text-[#4E5969] hover:bg-[#F7F8FA]"
          >
            {localize('com_app_start_chat')}
          </Button>
        </div>
      ) : (
        <div className="hidden h-[28px] w-full min-w-0 items-stretch justify-center gap-1 group-hover/card:flex coarse-pointer:flex">
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
          <Button
            onClick={(e) => {
              e.stopPropagation();
              onStartChat(agent);
            }}
            className="flex-1 min-w-0 justify-center items-center h-full max-h-full rounded-[6px] px-2 py-0 text-[14px] font-normal"
          >
            {localize('com_app_start_chat')}
          </Button>
        </div>
      )}
    </div>
  );
}