import { MoreHorizontal, Pin, Play } from 'lucide-react';
import type { AppItem } from '~/@types/app';
import AppAvator from '~/components/Avator';
import { cn } from '~/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '~/components/ui/DropdownMenu';
import { Button } from '~/components';

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
  return (
    <div
      className={cn(
        'group relative flex flex-col justify-between overflow-hidden rounded-[6px] border border-solid p-2 h-[132px] transition-all cursor-pointer',
        'border-[#ebecf0] border-[0.5px] hover:border-[#335cff] hover:border-[1.047px] hover:shadow-[0px_2.094px_8.796px_1.047px_rgba(117,145,212,0.12)] bg-white',
        'bg-[linear-gradient(123.519deg,_rgb(249,251,254)_0%,_rgb(255,255,255)_50%,_rgb(249,251,254)_100%)]',
      )}
      onClick={() => onStartChat(agent)}
    >
      {/* Header Info */}
      <div className="flex items-start justify-between w-full relative z-10 shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <AppAvator className="size-[32px] min-w-[20px] shrink-0 rounded-[4px]" url={agent.logo} id={agent.id as any} flowType={String(agent.flow_type)} />
          <p className="font-['PingFang_SC'] font-medium leading-[22px] text-[#212121] text-[14px] truncate">
            {agent.name}
          </p>
        </div>

        <div className="max-[576px]:hidden">
          <TooltipProvider delayDuration={200}>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    onTogglePin(agent);
                  }}
                  className={cn(
                    'flex items-center justify-center p-1 rounded-[6px] transition-colors shrink-0',
                    isPinned
                      ? 'border border-[#ececec]'
                      : 'opacity-0 group-hover:opacity-100 hover:border-[#ececec] hover:border',
                  )}
                >
                  <Pin
                    size={14}
                    className={cn('text-gray-400', isPinned ? 'fill-gray-400' : '')}
                  />
                </button>
              </TooltipTrigger>
              <TooltipContent>{isPinned ? '取消置顶' : '将应用置顶'}</TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <div className="hidden max-[576px]:flex items-center shrink-0">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button
                type="button"
                onClick={(e) => e.stopPropagation()}
                className="flex items-center justify-center p-1 rounded-[6px] border border-[#ececec] bg-white hover:bg-gray-50"
                aria-label="更多"
              >
                <MoreHorizontal size={16} className="text-gray-500" />
              </button>
            </DropdownMenuTrigger>

            <DropdownMenuContent align="end" className="p-1">
              <DropdownMenuItem
                className="py-2 px-3 rounded-lg"
                onClick={(e) => {
                  e.stopPropagation()
                  onShare(agent)
                }}
              >
                分享应用
              </DropdownMenuItem>
              <DropdownMenuItem
                className="py-2 px-3 rounded-lg"
                onClick={(e) => {
                  e.stopPropagation()
                  onTogglePin(agent)
                }}
              >
                {isPinned ? '取消置顶' : '置顶'}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* Description */}
      <div className="flex-1 font-['PingFang_SC'] text-[12px] text-[#a9aeb8] leading-[19.5px] overflow-hidden whitespace-normal break-words line-clamp-2 mt-2 mb-2 max-[576px]:hidden">
        {agent.description || '暂无描述内容...'}
      </div>

      {/* Tags + 开始对话（移动端：同一行；多余 tag 遮盖不滑动） */}
      <div className="flex gap-1 items-start mt-auto group-hover:hidden overflow-hidden flex-wrap h-[26px] max-[576px]:flex-nowrap max-[576px]:h-[28px] max-[576px]:items-center max-[576px]:group-hover:flex">
        <div className="flex gap-1 items-start overflow-hidden flex-wrap h-[26px] max-[576px]:flex-nowrap max-[576px]:flex-1 max-[576px]:min-w-0 max-[576px]:items-center max-[576px]:overflow-hidden">
          {agent.tags && agent.tags.length > 0 ? (
            agent.tags.slice(0, 3).map((tag, idx) => (
              <div
                key={idx}
                className="bg-[#f2f3f5] text-[#4e5969] px-2 py-0.5 rounded-[4px] text-[12px] font-['PingFang_SC'] leading-[20px] whitespace-nowrap shrink-0"
              >
                {tag.name}
              </div>
            ))
          ) : (
            <div className="bg-[#f2f3f5] text-[#4e5969] px-2 py-0.5 rounded-[4px] text-[12px] font-['PingFang_SC'] leading-[20px] whitespace-nowrap shrink-0">
              精选
            </div>
          )}
        </div>

        <Button
          variant="default"
          size="default"
          onClick={(e) => {
            e.stopPropagation()
            onStartChat(agent)
          }}
          className="hidden max-[576px]:flex shrink-0 items-center justify-center h-[28px] w-[56px] p-0 rounded-[6px] bg-[#335cff] hover:bg-[#335cff] text-white"
        >
          <Play className="size-4 shrink-0" aria-hidden />
          <span className="max-[576px]:sr-only">开始对话</span>
        </Button>
      </div>

      {/* Action Buttons (Visible only on hover) */}
      <div className="hidden group-hover:flex gap-1 items-center justify-center w-full mt-auto h-[28px] max-[576px]:hidden max-[576px]:group-hover:hidden">
        <Button
          onClick={(e) => {
            e.stopPropagation();
            onShare(agent);
          }}
          variant="outline"
          className="flex-1 flex justify-center items-center h-full rounded-[6px] text-[14px] "
        >
          分享应用
        </Button>
        <Button
          onClick={(e) => {
            e.stopPropagation();
            onStartChat(agent);
          }}
          className="flex-1 flex justify-center items-center h-full rounded-[6px] text-[14px]"
        >
          <Play className="size-4 shrink-0 hidden max-[576px]:block" aria-hidden />
          <span className="max-[576px]:sr-only">开始对话</span>
        </Button>
      </div>
    </div>
  );
}