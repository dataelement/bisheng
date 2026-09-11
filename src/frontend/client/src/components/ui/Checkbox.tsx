import * as React from 'react';
import { Checkbox as UICheckbox } from '@bisheng/ui';
import type { CheckboxProps } from '@bisheng/ui';
import { cn } from '~/utils';

/**
 * Re-export shim (packages/ui AGENTS DoD #3): the spec Checkbox now lives in
 * @bisheng/ui (组件-Checkbox复选框.md v1 — 14/16/18 ladder, 4px radius, gray→
 * brand state chain, three-signal disabled); call sites keep this import path.
 * Default size (medium, 16px) matches the old shadcn box, so bare call sites
 * render the same footprint.
 */

const Checkbox = React.forwardRef<HTMLButtonElement, CheckboxProps>(
  ({ className, ...props }, ref) => (
    // `peer` preserved: the old shadcn checkbox shipped it and legacy labels
    // style off `peer-*` (e.g. ExportModal's peer-disabled).
    <UICheckbox ref={ref} className={cn('peer', className)} {...props} />
  ),
);
Checkbox.displayName = 'Checkbox';

export { Checkbox };
export type { CheckboxProps };
