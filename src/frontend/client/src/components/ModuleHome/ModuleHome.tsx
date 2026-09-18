import { Segmented } from '@bisheng/ui';
import type { CSSProperties, ReactNode } from 'react';
import { useLayoutEffect, useRef } from 'react';
import { matchPath, useLocation, useNavigate } from 'react-router-dom';
import { useLocalize } from '~/hooks';
import { useWorkbenchHubs } from '~/layouts/useWorkbenchHubs';
import type { WorkbenchNavSection } from '~/layouts/useWorkbenchNavLinks';
import { cn } from '~/utils';

/**
 * Shared frame of the workbench module homes (知识空间 / 频道 / 应用 / 技能). Each module is
 * the same two views — 我的 (what the user created / joined / used) and 广场 (what they
 * can discover) — and the sidebar folds sibling modules into one hub entry (知识资讯 =
 * 知识空间 + 频道, 智能拓展 = 应用 + 技能), so every home shares one header row:
 *
 *   [知识空间 | 频道] │ [我的 | 广场] ················ 搜索 · 排序 · [创建]
 *
 *   left   ModuleHubSwitcher — the hub's modules, rendered ONCE by the shell (MainLayout)
 *          so moving between siblings slides its thumb; a module with no sibling shows
 *          its name there instead.
 *          ModuleViewTabs — 我的 / 广场, rendered once per page, right after it.
 *   right  the page's tools, passed to ModuleHomeHeader: the create button last, search
 *          and sort (where the page has them) before it.
 *
 * The two left controls live in different React trees (shell vs. page), so the shell
 * publishes the width of its part as a CSS variable on <main> and the page's tabs offset
 * themselves by it — no state crosses the KeepAlive boundary. Mobile is out of scope:
 * each module keeps its own mobile navigation.
 */
export type ModuleView = 'mine' | 'square';

/** Page padding + centered column every module home shares (see pages/apps). */
export const MODULE_HOME_FRAME =
  'flex h-full min-h-0 w-full flex-col items-center overflow-hidden bg-white px-3 py-5';
export const MODULE_HOME_COLUMN = 'w-full max-w-[1000px]';

/** Gap between the page's edge and the centered 1000px column — the same on both sides. */
const COLUMN_EDGE = 'calc((100% - min(1000px, 100% - 24px)) / 2)';

/** Width of the shell's part of the header row (module switcher or module name), set on
 *  <main> by ModuleHubSwitcher and read by ModuleViewTabs. */
const LEAD_WIDTH_VAR = '--module-home-lead-w';

/** Both switchers are pills here: track and thumb fully rounded (the thumb has no class
 *  hook of its own, hence the child selector). */
const PILL = 'rounded-full [&>span[aria-hidden]]:rounded-full';

// 36px controls centered on the 32px header row that starts 20px from the top.
const FLOATING_ROW = 'absolute top-[18px] z-20 flex h-9 items-center';

/** Pages that ARE a module's home — the only places the module switcher shows. A page
 *  deeper in a module (a space, a channel, a settings form) is left through the sidebar. */
const MODULE_HOME_PATHS: Partial<Record<WorkbenchNavSection, string[]>> = {
  knowledge: ['/knowledge'],
  channel: ['/channel'],
  apps: ['/apps', '/apps/explore'],
  skills: ['/skills'],
};

/**
 * The shell's part of the header row, at the column's left edge: the hub's module switcher
 * (with the modules' icons), or the module's name when it has no sibling to switch to.
 * It belongs to the SHELL, not to the pages: MainLayout renders one instance for every
 * module home, so going from one module to its sibling slides the thumb instead of
 * swapping two controls mounted by two different pages. Desktop only.
 */
export function ModuleHubSwitcher() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const hubs = useWorkbenchHubs();
  const rowRef = useRef<HTMLDivElement>(null);

  const current = Object.entries(MODULE_HOME_PATHS).find(([, paths]) =>
    paths.some((path) => matchPath({ path, end: true }, pathname) !== null),
  )?.[0];
  const hub = hubs.find((item) => item.modules.some((link) => link.section === current));
  const currentModule = hub?.modules.find((link) => link.section === current);

  // Publish this row's width on the positioned parent (<main>) so the page's 我的 / 广场
  // tabs can sit right after it. Re-measured when the labels change size (language,
  // fonts loading); cleared off a module home, where the row is hidden.
  useLayoutEffect(() => {
    const row = rowRef.current;
    const host = row?.parentElement;
    if (!row || !host) return undefined;
    const publish = () => host.style.setProperty(LEAD_WIDTH_VAR, `${row.offsetWidth}px`);
    publish();
    const observer = new ResizeObserver(publish);
    observer.observe(row);
    return () => {
      observer.disconnect();
      host.style.removeProperty(LEAD_WIDTH_VAR);
    };
  }, []);

  return (
    <div ref={rowRef} className={cn(FLOATING_ROW, !currentModule && 'hidden')} style={{ left: COLUMN_EDGE }}>
      {hub && currentModule && hub.modules.length > 1 ? (
        <Segmented
          size="large"
          className={PILL}
          aria-label={hub.label}
          options={hub.modules.map((link) => ({ value: link.section, label: link.label, icon: link.icon }))}
          value={currentModule.section}
          onChange={(next) => {
            const target = hub.modules.find((link) => link.section === next);
            if (target && next !== currentModule.section) navigate(target.to);
          }}
        />
      ) : currentModule ? (
        // Decorative: the page's own (visually hidden) <h1> is the heading of record.
        <span aria-hidden className="truncate text-[24px] font-semibold leading-8 text-blue-500">{currentModule.label}</span>
      ) : null}
    </div>
  );
}

interface ModuleViewTabsProps {
  active: ModuleView;
  onChange: (view: ModuleView) => void;
  disabled?: boolean;
  /** Override the default spot (right after the shell's part of the header row) — for
   *  pages inside a module that keep the switcher but have their own header geometry.
   *  Pass `left: 'auto'` along with a `right`. */
  style?: CSSProperties;
  className?: string;
}

/**
 * 我的 / 广场 switcher, led by the hairline that separates it from the module switcher.
 * Absolutely positioned against the nearest `relative` ancestor, which must be the page
 * root (full main-area width) for the default spot to be right. Render it ONCE per page,
 * above both views and with a stable `key`, so switching slides one indicator instead
 * of swapping two mounted controls.
 */
export function ModuleViewTabs({ active, onChange, disabled = false, style, className }: ModuleViewTabsProps) {
  const localize = useLocalize();
  return (
    <div
      className={cn(FLOATING_ROW, 'gap-3', className)}
      style={{ left: `calc(${COLUMN_EDGE} + var(${LEAD_WIDTH_VAR}, 0px) + 12px)`, ...style }}
    >
      <div aria-hidden className="h-4 w-px shrink-0 bg-border-base" />
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
  /** The page's heading of record. Not drawn: the shell's module switcher (or module
   *  name) already says where the user is, so this is for assistive tech. */
  title: string;
  /** The page's tools, right-aligned: search and sort where the page has them, then the
   *  create button LAST. All medium (32px) controls, so they sit on this row's height. */
  children?: ReactNode;
}

/** Header row of a 我的 view, 32px tall and 16px above the content. Its left half is
 *  covered by the floating switchers; its right half holds the page's tools. */
export function ModuleHomeHeader({ title, children }: ModuleHomeHeaderProps) {
  return (
    <header className={cn(MODULE_HOME_COLUMN, 'flex h-8 shrink-0 items-center justify-end gap-2')}>
      <h1 className="sr-only">{title}</h1>
      {children}
    </header>
  );
}
