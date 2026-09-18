import { Segmented } from '@bisheng/ui';
import type { CSSProperties, ReactNode } from 'react';
import { useLocalize } from '~/hooks';
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
 */
export type ModuleView = 'mine' | 'square';

/** Page padding + centered column every module home shares (see pages/apps). */
export const MODULE_HOME_FRAME =
  'flex h-full min-h-0 w-full flex-col items-center overflow-hidden bg-white px-3 py-5';
export const MODULE_HOME_COLUMN = 'w-full max-w-[1000px]';

/** Right edge of the centered 1000px column, measured from the page's right edge. */
const COLUMN_RIGHT_EDGE = 'calc((100% - min(1000px, 100% - 24px)) / 2)';

interface ModuleViewTabsProps {
  active: ModuleView;
  onChange: (view: ModuleView) => void;
  disabled?: boolean;
  /** Override the default spot (column's right edge, centered on the title row) — for
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
    <div
      // 36px control centered on the 32px title row that starts 20px from the top.
      className={cn('absolute top-[18px] z-20 flex h-9 items-center', className)}
      style={{ right: COLUMN_RIGHT_EDGE, ...style }}
    >
      <Segmented
        size="large"
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
  title: string;
  /** Sits right after the title. The row's right end belongs to ModuleViewTabs. */
  children?: ReactNode;
}

/** Title row of a 我的 view: 24px brand title, 32px tall, 16px above the content. */
export function ModuleHomeHeader({ title, children }: ModuleHomeHeaderProps) {
  return (
    <header className={cn(MODULE_HOME_COLUMN, 'flex h-8 shrink-0 items-center gap-4 pr-[220px]')}>
      <h1 className="min-w-0 truncate text-[24px] font-semibold leading-8 text-blue-500">{title}</h1>
      {children}
    </header>
  );
}
