import { Outlet } from 'react-router-dom';
import { MODULE_HOME_COLUMN, MODULE_HOME_FRAME, ModuleHomeHeader } from '~/components/ModuleHome';
import { usePrefersMobileLayout, useWorkbenchMenuNames } from '~/hooks';
import { cn } from '~/utils';

export function AppCenter() {
  const menuNames = useWorkbenchMenuNames();
  const isMobileLayout = usePrefersMobileLayout();

  return (
    <section className={cn(MODULE_HOME_FRAME, 'flex-1', isMobileLayout && 'px-4 pb-5 pt-3')}>
      {!isMobileLayout && <ModuleHomeHeader title={menuNames.apps} />}
      <div className={cn(MODULE_HOME_COLUMN, 'min-h-0 flex-1')}>
        <Outlet />
      </div>
    </section>
  );
}
