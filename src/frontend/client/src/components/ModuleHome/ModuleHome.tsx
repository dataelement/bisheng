import type { ReactNode } from 'react';
import { cn } from '~/utils';

/**
 * Shared frame of the workbench module homes (知识空间 / 频道 / 应用 / 技能). A module home is
 * what the user HAS — created, joined, used; what they can discover lives behind its own
 * sidebar entry (广场, ~/pages/square). Every home shares one header row:
 *
 *   知识空间 ········································ 搜索 · 排序 · [创建]
 *
 *   left   the module's name
 *   right  the page's tools: the create button last, search and sort (where the page has
 *          them) before it.
 *
 * Mobile is out of scope: each module keeps its own mobile navigation (and its own square).
 */

/** Page padding + centered column every module home shares (see pages/apps). */
export const MODULE_HOME_FRAME =
  'flex h-full min-h-0 w-full flex-col items-center overflow-hidden bg-white px-3 py-5';
export const MODULE_HOME_COLUMN = 'w-full max-w-[1000px]';

/** A pill-shaped Segmented: track and thumb fully rounded (the thumb has no class hook of
 *  its own, hence the child selector). Used by 广场's module tabs. */
export const MODULE_HOME_PILL = 'rounded-full [&>span[aria-hidden]]:rounded-full';

interface ModuleHomeHeaderProps {
  title: string;
  /** The page's tools, right-aligned: search and sort where the page has them, then the
   *  create button LAST. All medium (32px) controls, so they sit on this row's height. */
  children?: ReactNode;
}

/** Header row of a module home: 24px brand title, 32px tall, 16px above the content. */
export function ModuleHomeHeader({ title, children }: ModuleHomeHeaderProps) {
  return (
    <header className={cn(MODULE_HOME_COLUMN, 'flex h-8 shrink-0 items-center gap-4')}>
      <h1 className="min-w-0 flex-1 truncate text-[24px] font-semibold leading-8 text-blue-500">{title}</h1>
      {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
    </header>
  );
}
