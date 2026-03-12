import { ArrowLeftRight, Loader2, Search } from 'lucide-react';
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
      className="p-1 text-gray-300 hover:text-gray-500 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
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
        className="w-[260px] p-0 max-h-[400px] flex flex-col"
      >
        {/* Search input */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-gray-100">
          <Search size={14} className="text-gray-400 flex-shrink-0" />
          <input
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索应用..."
            className="flex-1 bg-transparent outline-none text-sm"
            autoFocus
          />
        </div>

        {/* App list */}
        <div className="overflow-y-auto py-1 max-h-[340px]">
          {loading ? (
            <div className="flex items-center justify-center py-6">
              <Loader2 size={20} className="animate-spin text-gray-400" />
            </div>
          ) : allApps.length === 0 ? (
            <div className="text-center py-6 text-sm text-gray-400">
              未找到相关应用
            </div>
          ) : (
            allApps.map((app: AppItem) => (
              <button
                key={app.id}
                onClick={() => switchApp(app)}
                className={cn(
                  'w-full flex items-center gap-3 px-3 py-2 text-left hover:bg-gray-50 transition-colors',
                  app.id === currentFlowId && 'bg-blue-50',
                )}
              >
                <AppAvator
                  className="size-8 min-w-8"
                  url={app.logo}
                  id={app.id as any}
                  flowType={String(app.flow_type)}
                />
                <span className="text-sm text-gray-700 truncate">{app.name}</span>
              </button>
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
