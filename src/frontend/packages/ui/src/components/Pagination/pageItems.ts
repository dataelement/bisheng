/**
 * Which page buttons the standard pager shows (组件-Pagination分页.md §3.1).
 *
 * - ≤ 7 pages: every page, no ellipsis.
 * - more: first and last always; the current page with 2 neighbours on each
 *   side; the rest becomes an ellipsis. The window is clipped at the edges and
 *   never padded inward (page 1 shows `1 2 3 … 13`, not `1 2 3 4 5 … 13`).
 * - An ellipsis only ever stands in for 2 pages or more — a gap of exactly one
 *   page shows that page, since the `…` would take the same room anyway.
 */
export type PageItem = number | 'ellipsis-start' | 'ellipsis-end';

/** §3.1 — up to this many pages, every page is shown. */
const SHOW_ALL_UP_TO = 7;

/** §3.1 — neighbours kept on each side of the current page. */
const SIBLINGS = 2;

export function getPageItems(current: number, totalPages: number): PageItem[] {
  if (totalPages <= SHOW_ALL_UP_TO) {
    return Array.from({ length: totalPages }, (_, i) => i + 1);
  }

  let start = Math.max(2, current - SIBLINGS);
  let end = Math.min(totalPages - 1, current + SIBLINGS);
  // A gap of one page shows the page itself instead of an ellipsis.
  if (start === 3) start = 2;
  if (end === totalPages - 2) end = totalPages - 1;

  const items: PageItem[] = [1];
  if (start > 2) items.push('ellipsis-start');
  for (let page = start; page <= end; page += 1) items.push(page);
  if (end < totalPages - 1) items.push('ellipsis-end');
  items.push(totalPages);
  return items;
}
