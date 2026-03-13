import { Pin } from 'lucide-react';
import type { AppItem } from '~/@types/app';
import AppAvator from '~/components/Avator';
import { cn } from '~/utils';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';

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
          <AppAvator className="size-[20px] min-w-[20px] shrink-0 rounded-[4px]" url={agent.logo} id={agent.id as any} flowType={String(agent.flow_type)} />
          <p className="font-['PingFang_SC'] font-medium leading-[22px] text-[#212121] text-[14px] truncate">
            {agent.name}
          </p>
        </div>

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

      {/* Description */}
      <div className="flex-1 font-['PingFang_SC'] text-[12px] text-[#a9aeb8] leading-[19.5px] overflow-hidden whitespace-normal break-words line-clamp-2 mt-2 mb-2">
        {agent.description || '暂无描述内容...'}
      </div>

      {/* Tags (Hidden on hover) */}
      <div className="flex gap-1 items-start mt-auto group-hover:hidden overflow-hidden flex-wrap h-[26px]">
        {agent.tags && agent.tags.length > 0 ? (
          agent.tags.slice(0, 3).map((tag, idx) => (
            <div
              key={idx}
              className="bg-[#f2f3f5] text-[#4e5969] px-2 py-0.5 rounded-[4px] text-[12px] font-['PingFang_SC'] leading-[20px] whitespace-nowrap"
            >
              {tag.name}
            </div>
          ))
        ) : (
          <div className="bg-[#f2f3f5] text-[#4e5969] px-2 py-0.5 rounded-[4px] text-[12px] font-['PingFang_SC'] leading-[20px] whitespace-nowrap">
            精选
          </div>
        )}
      </div>

      {/* Action Buttons (Visible only on hover) */}
      <div className="hidden group-hover:flex gap-1 items-center justify-center w-full mt-auto h-[26px]">
        <button
          onClick={(e) => {
            e.stopPropagation();
            onShare(agent);
          }}
          className="flex-1 bg-white border border-[#ececec] text-[#212121] flex justify-center items-center h-full rounded-[6px] text-[14px] font-['PingFang_SC'] hover:bg-gray-50 transition-colors"
        >
          分享应用
        </button>
        <button
          onClick={(e) => {
            e.stopPropagation();
            onStartChat(agent);
          }}
          className="flex-1 bg-[#335cff] text-white flex justify-center items-center h-full rounded-[6px] text-[14px] font-['PingFang_SC'] hover:bg-blue-600 transition-colors"
        >
          开始对话
        </button>
      </div>
    </div>
  );
}