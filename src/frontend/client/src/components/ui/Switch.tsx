import * as React from 'react';
import { Switch as UISwitch } from '@bisheng/ui';
import type { SwitchProps as UISwitchProps } from '@bisheng/ui';
import { cn } from '~/utils';

/**
 * Re-export shim (packages/ui AGENTS DoD #3): the spec Switch now lives in
 * @bisheng/ui (组件-Switch开关.md v1 — 22×38 / 18×32, brand track, loading,
 * inner text); call sites keep this import path.
 */

export interface SwitchProps extends UISwitchProps {
  /**
   * @deprecated Legacy skin knob (`tool` was the narrow 20×34 chat-tools
   * look). The spec switch has ONE skin — both values render it; accepted so
   * old call sites compile unchanged. Will be dropped with the call-site
   * migration batch.
   */
  variant?: 'default' | 'tool';
}

const Switch = React.forwardRef<HTMLButtonElement, SwitchProps>(
  ({ variant, className, ...props }, ref) => {
    void variant; // legacy — see the deprecation note above
    // `peer` preserved: the old shadcn switch shipped it and legacy labels
    // style off `peer-*`.
    return <UISwitch ref={ref} className={cn('peer', className)} {...props} />;
  },
);
Switch.displayName = 'Switch';

export { Switch };
