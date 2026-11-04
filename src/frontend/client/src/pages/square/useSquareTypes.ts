import type { ReactNode } from 'react';
import { useWorkbenchNavLinks } from '~/layouts/useWorkbenchNavLinks';
import { SQUARE_TYPES, type SquareType } from './squarePaths';

export interface SquareTypeEntry {
  type: SquareType;
  label: string;
  icon: ReactNode;
}

/**
 * The squares this account may open, in tab order: one per module it is granted. A module
 * that is only listed so the user can apply for it (menu-approval mode) has no square yet.
 */
export function useSquareTypes(): SquareTypeEntry[] {
  const { links } = useWorkbenchNavLinks();
  return SQUARE_TYPES.flatMap((type) => {
    const link = links.find((item) => item.section === type);
    if (!link || link.to.startsWith('/menu-unavailable')) return [];
    return [{ type, label: link.label, icon: link.icon }];
  });
}
