import { Segmented } from '@bisheng/ui';
import type { CSSProperties, ReactNode } from 'react';
import { matchPath, useLocation, useNavigate } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import { useWorkbenchHubs } from '~/layouts/useWorkbenchHubs';
import type { WorkbenchNavSection } from '~/layouts/useWorkbenchNavLinks';
import { cn } from '~/utils';

/**
 * Shared frame of the three workbench module homes (知识空间 / 应用 / 频道). Each module is
 * the same two views — 我的 (what the user created / joined / used) and 广场 (what they
 * can discover) — so the desktop structure is one pattern:
 *
 *   我的:  ModuleHomeHeader (module title, left) + ModuleViewTabs (right), content below
 *   广场:  the module's square banner page, with the same ModuleViewTabs floating over it
 *
 * The switcher sits at the same spot in both views and replaces every per-module way of
 * getting to the square and back (links, header buttons, banner back arrows). Mobile is
 * out of scope: each module keeps its own mobile navigation.
 *
 * The sidebar folds sibling modules into one hub entry (知识资讯 = 知识空间 + 频道, 智能拓展 =
 * 应用 + 技能), so the header row also carries the hub's module switcher, in the title's
 * place — rendered by the shell, see ModuleHubSwitcher:
 *   [知识空间 | 频道] ················ [我的 | 广场]
 */
export type ModuleView = 'mine' | 'square';

/** Page padding + centered column every module home shares (see pages/apps). */
export const MODULE_HOME_FRAME =
  'flex h-full min-h-0 w-full flex-col items-center overflow-hidden bg-white px-3 py-5';
export const MODULE_HOME_COLUMN = 'w-full max-w-[1000px]';

/** Gap between the page's edge and the centered 1000px column — the same on both sides. */
const COLUMN_EDGE = 'calc((100% - min(1000px, 100% - 24px)) / 2)';

/** Both switchers are pills here: track and thumb fully rounded (the thumb has no class
 *  hook of its own, hence the child selector). */
const PILL = 'rounded-full [&>span[aria-hidden]]:rounded-full';

// 36px controls centered on the 32px header row that starts 20px from the top.
const FLOATING_ROW = 'absolute top-[18px] z-20 flex h-9 items-center';

/** The hub `module` belongs to, when it has siblings the user may open. */
function useModuleHub(module: WorkbenchNavSection) {
  const hub = useWorkbenchHubs().find((item) => item.modules.some((link) => link.section === module));
  return hub && hub.modules.length > 1 ? hub : undefined;
}

/** Pages that ARE a module's home — the only places the module switcher shows. A page
 *  deeper in a module (a space, a channel, a settings form) is left through the sidebar. */
const MODULE_HOME_PATHS: Partial<Record<WorkbenchNavSection, string[]>> = {
  knowledge: ['/knowledge'],
  channel: ['/channel'],
  apps: ['/apps', '/apps/explore'],
  skills: ['/skills'],
};

/**
 * The hub's module switcher (with the modules' icons), at the column's left edge where a
 * page title would sit. It belongs to the SHELL, not to the pages: MainLayout renders one
 * instance for every module home, so going from one module to its sibling slides the
 * thumb instead of swapping two controls mounted by two different pages. Desktop only.
 */
export function ModuleHubSwitcher() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const hubs = useWorkbenchHubs();

  const current = Object.entries(MODULE_HOME_PATHS).find(([, paths]) =>
    paths.some((path) => matchPath({ path, end: true }, pathname) !== null),
  )?.[0];
  const hub = hubs.find((item) => item.modules.some((link) => link.section === current));
  if (!current || !hub || hub.modules.length < 2) return null;

  return (
    <div className={FLOATING_ROW} style={{ left: COLUMN_EDGE }}>
      <Segmented
        size="large"
        className={PILL}
        aria-label={hub.label}
        options={hub.modules.map((link) => ({ value: link.section, label: link.label, icon: link.icon }))}
        value={current}
        onChange={(next) => {
          const target = hub.modules.find((link) => link.section === next);
          if (target && next !== current) navigate(target.to);
        }}
      />
    </div>
  );
}

interface ModuleViewTabsProps {
  active: ModuleView;
  onChange: (view: ModuleView) => void;
  disabled?: boolean;
  /** Override the default spot (column's right edge, centered on the header row) — for
   *  pages inside a module that keep the switcher but have their own header geometry. */
  style?: CSSProperties;
  className?: string;
}

/**
 * 我的 / 广场 switcher. Absolutely positioned against the nearest `relative` ancestor,
 * which must be the page root (full main-area width) for the default spot to be right.
 * Render it ONCE per page, above both views and with a stable `key`, so switching
 * slides one indicator instead of swapping two mounted controls.
 */
export function ModuleViewTabs({ active, onChange, disabled = false, style, className }: ModuleViewTabsProps) {
  const localize = useLocalize();
  return (
    <div className={cn(FLOATING_ROW, className)} style={{ right: COLUMN_EDGE, ...style }}>
      <Segmented
        size="large"
        className={PILL}
        options={[
          { value: 'mine', label: localize('com_module_home.tab_mine') },
          { value: 'square', label: localize('com_module_home.tab_square') },
        ]}
        value={active}
        onChange={(next) => {
          if (next !== active) onChange(next as ModuleView);
        }}
        disabled={disabled}
      />
    </div>
  );
}

interface ModuleHomeHeaderProps {
  /** The module this page belongs to. Inside a hub the module switcher takes the title's
   *  place, so the row only keeps its height (and a screen-reader heading). */
  module: WorkbenchNavSection;
  title: string;
  /** Sits right after the title. The row's right end belongs to ModuleViewTabs. */
  children?: ReactNode;
}

/** Header row of a 我的 view, 32px tall and 16px above the content: the module switcher
 *  floats over it inside a hub; a module standing alone shows its 24px brand title. */
export function ModuleHomeHeader({ module, title, children }: ModuleHomeHeaderProps) {
  const hub = useModuleHub(module);
  return (
    <header className={cn(MODULE_HOME_COLUMN, 'flex h-8 shrink-0 items-center gap-4 pr-[220px]')}>
      <h1 className={hub ? 'sr-only' : 'min-w-0 truncate text-[24px] font-semibold leading-8 text-blue-500'}>
        {title}
      </h1>
      {children}
    </header>
  );
}
