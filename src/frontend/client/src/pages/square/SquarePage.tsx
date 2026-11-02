import { Segmented } from '@bisheng/ui';
import { lazy, Suspense } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { MODULE_HOME_COLUMN, MODULE_HOME_PILL } from '~/components/ModuleHome';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { useLocalize, usePrefersMobileLayout } from '~/hooks';
import { cn } from '~/utils';
import { useSquareTypes } from './useSquareTypes';
import type { SquareType } from './squarePaths';

// One chunk per square: opening discovery only loads the tab in view.
const PANES: Record<SquareType, ReturnType<typeof lazy>> = {
  knowledge: lazy(() => import('~/pages/knowledge/KnowledgeSquarePane').then((module) => ({ default: module.KnowledgeSquarePane }))),
  channel: lazy(() => import('~/pages/Subscription/ChannelSquarePane').then((module) => ({ default: module.ChannelSquarePane }))),
  apps: lazy(() => import('~/pages/apps/explore')),
  skills: lazy(() => import('~/pages/skills/SkillSquarePane').then((module) => ({ default: module.SkillSquarePane }))),
};

/**
 * The discover side of every workbench module behind one sidebar entry, so the
 * module homes are only ever "mine". The tabs are the modules this account may open;
 * each tab hosts that module's existing square unchanged (its own banner, search, cards
 * and preview drawer).
 */
export function SquarePage() {
  const localize = useLocalize();
  const isMobile = usePrefersMobileLayout();
  const types = useSquareTypes();
  const [params, setParams] = useSearchParams();

  if (types.length === 0) return <Navigate to="/" replace />;
  const requested = params.get('type');
  const active = types.find((item) => item.type === requested) ?? types[0];
  const Pane = PANES[active.type];

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-white">
      {types.length > 1 && (
        // Keep the banner's height while sharing the top row with the mobile menu.
        <div
          className={cn(
            'flex w-full shrink-0 justify-center bg-blue-500/[0.05] px-3 pb-[14px] pt-[18px]',
            isMobile && 'px-[52px] pt-[calc(env(safe-area-inset-top,0px)+18px)]',
          )}
        >
          <div className={cn(MODULE_HOME_COLUMN, 'flex h-9 min-w-0 items-center justify-center')}>
            <Segmented
              block
              size="large"
              className={cn(
                MODULE_HOME_PILL,
                'min-w-0',
                isMobile
                  ? '[&>button]:min-w-0 [&>button]:px-2 [&>button>svg]:shrink-0'
                  : 'max-w-fit',
              )}
              aria-label={localize('com_workbench_sidebar.square')}
              options={types.map((item) => ({
                value: item.type,
                label: <span className="min-w-0 truncate" title={item.label}>{item.label}</span>,
                icon: item.icon,
              }))}
              value={active.type}
              onChange={(next) => {
                // A fresh query: the other params (`?skill=`) belong to the tab being left.
                if (next !== active.type) setParams({ type: next }, { replace: true });
              }}
            />
          </div>
        </div>
      )}
      <div className="min-h-0 w-full flex-1 overflow-hidden">
        <Suspense
          fallback={
            <div className="flex h-full w-full items-center justify-center">
              <LoadingIcon className="size-16 text-blue-500" />
            </div>
          }
        >
          <Pane key={active.type} />
        </Suspense>
      </div>
    </div>
  );
}
