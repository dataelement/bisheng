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
  /** The narrow shell already displays the title; this row holds its tools only. */
  mobileTitleInShell?: boolean;
  /** The page's tools, right-aligned: search and sort where the page has them, then the
   *  create button LAST. All medium (32px) controls, so they sit on this row's height. */
  children?: ReactNode;
}

/** Header row of a module home: 32px tall, 16px above the content. The title takes the
 *  sidebar wordmark's voice — same semibold, same neutral text-1, one step up the
 *  ladder (text-h2, 20/28) so the page still outranks the shell — and leaves the brand
 *  color to what the user acts on: the create button on this same row. */
export function ModuleHomeHeader({ title, children, mobileTitleInShell = false }: ModuleHomeHeaderProps) {
  return (
    <header className={cn(MODULE_HOME_COLUMN, 'flex min-w-0 h-8 shrink-0 items-center gap-4', mobileTitleInShell && 'max-[767px]:h-auto')}>
      <h1 className={cn('min-w-0 flex-1 truncate text-h2 font-semibold text-text-1', mobileTitleInShell && 'max-[767px]:sr-only')}>{title}</h1>
      {children ? <div className={cn('flex shrink-0 items-center gap-2', mobileTitleInShell && 'max-[767px]:min-w-0 max-[767px]:flex-1')}>{children}</div> : null}
    </header>
  );
}
