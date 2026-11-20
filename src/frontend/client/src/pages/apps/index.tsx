import { Tabs } from '@bisheng/ui';
import { useLayoutEffect, useRef } from 'react';
import { useMatch, useNavigate, useOutlet } from 'react-router-dom';
import { MODULE_HOME_COLUMN, MODULE_HOME_FRAME, MODULE_HOME_TOOLBAR, ModuleHomeHeader } from '~/components/ModuleHome';
import { useLocalize, usePrefersMobileLayout, useWorkbenchMenuNames } from '~/hooks';
import { cn } from '~/utils';

const WORKBENCH_PATH = '/apps/cloud-workbenches';

export function AppCenter() {
  const localize = useLocalize();
  const menuNames = useWorkbenchMenuNames();
  const isMobileLayout = usePrefersMobileLayout();
  const navigate = useNavigate();
  const outlet = useOutlet();
  const activeKey = useMatch(WORKBENCH_PATH) ? 'workbenches' : 'bisheng';
  const requestedTab = useRef(activeKey);
  useLayoutEffect(() => {
    requestedTab.current = activeKey;
  }, [activeKey]);

  const handleTabChange = (key: string) => {
    if (key !== 'bisheng' && key !== 'workbenches') return;
    // Pointer selection can trigger both mouse down and automatic focus activation.
    if (requestedTab.current === key) return;
    requestedTab.current = key;
    navigate(key === 'workbenches' ? WORKBENCH_PATH : '/apps');
  };

  return (
    <section className={cn(MODULE_HOME_FRAME, 'flex-1', isMobileLayout && 'px-4 pb-5 pt-3')}>
      {!isMobileLayout && <ModuleHomeHeader title={menuNames.apps} />}
      <Tabs
        aria-label={menuNames.apps}
        size="large"
        className={cn(MODULE_HOME_COLUMN, MODULE_HOME_TOOLBAR, 'grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)]', !isMobileLayout && 'mt-2')}
        activeKey={activeKey}
        onChange={handleTabChange}
        items={[
          { key: 'bisheng', label: localize('com_app.bisheng_apps'), children: activeKey === 'bisheng' ? outlet : null },
          { key: 'workbenches', label: localize('shared:cloudWorkbenches.title'), children: activeKey === 'workbenches' ? outlet : null },
        ]}
      />
    </section>
  );
}
