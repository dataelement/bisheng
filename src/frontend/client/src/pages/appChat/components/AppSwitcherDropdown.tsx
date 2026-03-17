import { ArrowLeftRight, Loader2, Search, Pin } from 'lucide-react';
import type { AppItem } from '~/@types/app';
import { Popover, PopoverContent, PopoverTrigger } from '~/components/ui/Popover';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '~/components/ui/Tooltip2';
import { cn } from '~/utils';
import AppAvator from '~/components/Avator';
import { useAppSwitcher } from '~/pages/appChat/hooks/useAppSwitcher';

/**
 * App switcher dropdown built with Popover + custom search input.
 * No cmdk or heavy dependencies — all filtering handled in useAppSwitcher hook.
 */
export function AppSwitcherDropdown() {
  const {
    allApps,
    searchQuery,
    setSearchQuery,
    loading,
    open,
    setOpen,
    disabled,
    currentFlowId,
    switchApp,
  } = useAppSwitcher();

  const trigger = (
    <button
      disabled={disabled}
      className="p-1 text-gray-400 hover:text-gray-500 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
    >
      <ArrowLeftRight size={14} />
    </button>
  );

  // When disabled, just show tooltip with no popover
  if (disabled) {
    return (
      <TooltipProvider delayDuration={200}>
        <Tooltip>
          <TooltipTrigger asChild>{trigger}</TooltipTrigger>
          <TooltipContent>暂无可切换应用</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent
        align="start"
        sideOffset={6}
        className="w-[240px] p-0 bg-white shadow-[0px_4px_16px_rgba(0,0,0,0.08)] border border-[#ebecf0] rounded-[8px] flex flex-col overflow-hidden"
      >
        {/* Search input */}
        <div className="px-[12px] pt-[12px] pb-[8px] shrink-0">
          <div className="flex items-center gap-[6px] h-[28px] px-[8px] border border-[#ebecf0] rounded-[6px] focus-within:border-[#335cff] transition-colors">
            <Search size={14} className="text-[#a9aeb8] shrink-0" />
            <input
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="搜索知识库名称"
              className="flex-1 bg-transparent border-none outline-none text-[13px] text-[#212121] placeholder:text-[#a9aeb8]"
              autoFocus
            />
          </div>
        </div>

        {/* App list */}
        <div className="flex-1 overflow-y-auto px-[8px] pb-[8px] flex flex-col gap-[4px] max-h-[268px]">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 size={16} className="animate-spin text-gray-400" />
            </div>
          ) : allApps.length === 0 ? (
            <div className="text-center py-6 text-[13px] text-gray-400">
              未找到相关应用
            </div>
          ) : (
            allApps.map((app: AppItem & { is_pinned?: boolean; top?: boolean }) => {
              const isActive = app.id === currentFlowId;
              const isPinned = app.is_pinned || app.top; // Support existing pin fields if any

              return (
                <button
                  key={app.id}
                  onClick={() => switchApp(app)}
                  className={cn(
                    'w-full flex items-center justify-between h-[32px] px-[4px] py-[5px] rounded-[6px] hover:bg-[#f2f3f5] transition-colors group cursor-pointer text-left',
                    isActive && 'bg-[#f2f3f5]'
                  )}
                >
                  <div className="flex items-center gap-[8px] min-w-0 flex-1">
                    <AppAvator
                      className="size-[20px] min-w-[20px] rounded-[4px]"
                      iconClassName="w-3.5 h-3.5"
                      url={app.logo}
                      id={app.id as any}
                      flowType={String(app.flow_type || app.type)}
                    />
                    <span className="text-[14px] text-[#212121] leading-[22px] truncate">
                      {app.name}
                    </span>
                  </div>

                  {isPinned && (
                    <div className="shrink-0 size-[22px] flex items-center justify-center ml-[4px]">
                      <Pin size={14} className="text-[#335cff] fill-[#335cff]" />
                    </div>
                  )}
                </button>
              );
            })
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
