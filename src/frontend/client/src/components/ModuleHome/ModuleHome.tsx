import type { ReactNode } from 'react';
import { cn } from '~/utils';

/**
 * Shared frame of the workbench module homes (知识空间 / 频道 / 应用 / 技能): what the user
 * HAS — created, joined, used. Every home shares one header row:
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

interface ModuleHomeHeaderProps {
  title: string;
  /** The page's tools, right-aligned: search and sort where the page has them, then the
   *  create button LAST. All medium (32px) controls, so they sit on this row's height. */
  children?: ReactNode;
}

/** Header row of a module home: 32px tall, 16px above the content. The title takes the
 *  sidebar wordmark's voice — same semibold, same neutral text-1, one step up the
 *  ladder (text-h2, 20/28) so the page still outranks the shell — and leaves the brand
 *  color to what the user acts on: the create button on this same row. */
export function ModuleHomeHeader({ title, children }: ModuleHomeHeaderProps) {
  return (
    <header className={cn(MODULE_HOME_COLUMN, 'flex h-8 shrink-0 items-center gap-4')}>
      <h1 className="min-w-0 flex-1 truncate text-h2 font-semibold text-text-1">{title}</h1>
      {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
    </header>
  );
}
