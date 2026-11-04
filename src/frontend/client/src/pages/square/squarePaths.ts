import type { WorkbenchNavSection } from '~/layouts/useWorkbenchNavLinks';

/** Modules that have a square, in tab order. */
export const SQUARE_TYPES = ['knowledge', 'channel', 'apps', 'skills'] as const satisfies readonly WorkbenchNavSection[];
export type SquareType = (typeof SQUARE_TYPES)[number];

/** 广场 — every module's discover view behind one entry; `?type=` picks the module. */
export const squarePath = '/square';

export function squareTypePath(type: SquareType): string {
  return `${squarePath}?type=${type}`;
}
