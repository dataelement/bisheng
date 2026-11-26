import type { ReactNode } from 'react';
import usePrefersMobileLayout from '~/hooks/usePrefersMobileLayout';
import cn from '~/utils/cn';
import styles from './ModuleHome.module.css';

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

/** Browser geometry is the default; the desktop host uses the plugin-page geometry. */
export const MODULE_HOME_FRAME =
  `${styles.frame} ${styles.home} flex h-full min-h-0 min-w-0 w-full flex-col items-center overflow-hidden bg-white px-3 py-5 min-[768px]:p-8`;
export const MODULE_HOME_COLUMN = `${styles.column} w-full max-w-[1000px]`;
/** Desktop-only geometry hooks shared with a module's detail page. */
export const MODULE_PAGE_DESKTOP_FRAME = styles.frame;
export const MODULE_PAGE_DESKTOP_COLUMN = styles.column;
export const MODULE_HOME_TOOLBAR = styles.toolbar;
export const MODULE_HOME_BODY = styles.body;
export const MODULE_HOME_INTRO = styles.intro;
export const MODULE_HOME_GROUPS = styles.groups;
export const MODULE_HOME_SEARCH = styles.search;

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

/** A 32px header with a compact title (20/28, medium), aligned to the content. */
export function ModuleHomeHeader({ title, children, mobileTitleInShell = false }: ModuleHomeHeaderProps) {
  const isNarrowViewport = usePrefersMobileLayout();
  const compactHeader = mobileTitleInShell && isNarrowViewport;
  return (
    <header className={cn(MODULE_HOME_COLUMN, styles.header, 'flex min-w-0 h-8 shrink-0 items-center gap-4', compactHeader && 'h-auto')}>
      <h1 className={cn('min-w-0 flex-1 truncate text-h2 font-medium text-text-1', compactHeader && 'sr-only')}>{title}</h1>
      {children ? <div className={cn(styles.actions, 'flex shrink-0 items-center gap-2', compactHeader && 'min-w-0 flex-1')}>{children}</div> : null}
    </header>
  );
}
