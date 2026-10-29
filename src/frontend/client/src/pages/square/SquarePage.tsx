import { Segmented } from '@bisheng/ui';
import { lazy, Suspense } from 'react';
import { Navigate, useSearchParams } from 'react-router-dom';
import { MODULE_HOME_COLUMN, MODULE_HOME_PILL } from '~/components/ModuleHome';
import { LoadingIcon } from '~/components/ui/icon/Loading';
import { useLocalize } from '~/hooks';
import { cn } from '~/utils';
import { useSquareTypes } from './useSquareTypes';
import type { SquareType } from './squarePaths';

// One chunk per square: opening 广场 only loads the tab in view.
const PANES: Record<SquareType, ReturnType<typeof lazy>> = {
  knowledge: lazy(() => import('~/pages/knowledge/KnowledgeSquarePane').then((module) => ({ default: module.KnowledgeSquarePane }))),
  channel: lazy(() => import('~/pages/Subscription/ChannelSquarePane').then((module) => ({ default: module.ChannelSquarePane }))),
  apps: lazy(() => import('~/pages/apps/explore')),
  skills: lazy(() => import('~/pages/skills/SkillSquarePane').then((module) => ({ default: module.SkillSquarePane }))),
};

/**
 * 广场 — the discover side of every workbench module behind ONE sidebar entry, so the
 * module homes are only ever "mine". The tabs are the modules this account may open;
 * each tab hosts that module's existing square unchanged (its own banner, search, cards
 * and preview drawer). Desktop only: mobile keeps each module's own square.
 */
export function SquarePage() {
  const localize = useLocalize();
  const types = useSquareTypes();
  const [params, setParams] = useSearchParams();

  if (types.length === 0) return <Navigate to="/" replace />;
  const requested = params.get('type');
  const active = types.find((item) => item.type === requested) ?? types[0];
  const Pane = PANES[active.type];

  return (
    <div className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-white">
      {types.length > 1 && (
        // A row of its own, centered over the banners' centered titles. It cannot float over
        // the banner — four segments reach the title — so it wears the banners' own brand
        // tint instead, and the two read as one surface.
        <div className="flex w-full shrink-0 justify-center bg-blue-500/[0.05] px-3 pb-[14px] pt-[18px]">
          <div className={cn(MODULE_HOME_COLUMN, 'flex h-9 items-center justify-center')}>
            <Segmented
              size="large"
              className={MODULE_HOME_PILL}
              aria-label={localize('com_workbench_sidebar.square')}
              options={types.map((item) => ({ value: item.type, label: item.label, icon: item.icon }))}
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
