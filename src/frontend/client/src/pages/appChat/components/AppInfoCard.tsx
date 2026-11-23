import { Button, Tooltip, TooltipProvider } from '@bisheng/ui';
import { useLayoutEffect, useRef, useState } from 'react';
import type { AppItem } from '~/@types/app';
import AppAvator from '~/components/Avator';
import { useLocalize } from '~/hooks';
import { appCardSurfaceClassName } from '~/pages/apps/components/appCardStyles';
import { cn } from '~/utils';
import { AppSwitcherDropdown } from './AppSwitcherDropdown';

interface AppInfoCardProps {
  app: Pick<AppItem, 'name' | 'description' | 'logo' | 'flow_type' | 'can_share'> | null;
  actionSize?: 'small' | 'medium';
  onShare: () => void;
  onNewChat: () => void;
}

function AppDescription({ text }: { text: string }) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [truncated, setTruncated] = useState(false);

  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    const measure = () => setTruncated(element.scrollWidth > element.clientWidth + 1);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [text, truncated]);

  const description = (
    <p ref={ref} className={cn('truncate text-caption text-text-3', truncated && 'cursor-default')}>
      {text}
    </p>
  );

  return truncated ? (
    <TooltipProvider delayDuration={300}>
      <Tooltip content={text} side="bottom" align="start">
        {description}
      </Tooltip>
    </TooltipProvider>
  ) : description;
}

export function AppInfoCard({ app, actionSize = 'medium', onShare, onNewChat }: AppInfoCardProps) {
  const localize = useLocalize();
  const shareLabel = localize('com_app_share_app');
  const newChatLabel = localize('com_knowledge_start_new_chat');

  return (
    <div className={cn(appCardSurfaceClassName, 'flex flex-col gap-3')}>
      <div className="flex items-center gap-2">
        <AppAvator className="size-8 shrink-0 rounded-md" url={app?.logo} flowType={app?.flow_type} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-1">
            <h3 className="truncate text-body font-medium text-text-1">
              {app?.name || localize('com_app.unknown_name')}
            </h3>
            <div className="flex size-4 shrink-0 items-center justify-center">
              <AppSwitcherDropdown />
            </div>
          </div>
          <AppDescription text={app?.description || localize('com_app_no_description_placeholder')} />
        </div>
      </div>

      <div className="flex gap-2">
        {app?.can_share === true ? (
          <Button type="button" color="default" size={actionSize} className="min-w-0 flex-1" onClick={onShare}>
            <span className="truncate" title={shareLabel}>{shareLabel}</span>
          </Button>
        ) : null}
        <Button type="button" color="default" size={actionSize} className="min-w-0 flex-1" onClick={onNewChat}>
          <span className="truncate" title={newChatLabel}>{newChatLabel}</span>
        </Button>
      </div>
    </div>
  );
}
