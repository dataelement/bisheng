import * as React from 'react';
import * as SwitchPrimitives from '@radix-ui/react-switch';
import { cn } from '~/utils';

type SwitchVariant = 'default' | 'tool';

interface SwitchProps
  extends React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root> {
  /**
   * `default` keeps the original track size (h-5 w-10) and theme color.
   * `tool` follows the design spec for the chat tools menu: a narrower
   * 34px track with the #335CFF checked color. Both variants use a 16px
   * circular thumb.
   */
  variant?: SwitchVariant;
}

const Switch = React.forwardRef<
  React.ElementRef<typeof SwitchPrimitives.Root>,
  SwitchProps
>(({ className, variant = 'default', ...props }, ref) => {
  const isTool = variant === 'tool';
  return (
    <SwitchPrimitives.Root
      className={cn(
        'peer inline-flex h-5 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50',
        isTool
          ? 'w-[34px] data-[state=checked]:bg-blue-500 data-[state=unchecked]:bg-[#eeeeee]'
          : 'w-10 data-[state=checked]:bg-primary data-[state=unchecked]:bg-switch-unchecked',
        className,
      )}
      {...props}
      ref={ref}
    >
      <SwitchPrimitives.Thumb
        className={cn(
          'pointer-events-none block size-4 rounded-full bg-background shadow-lg ring-0 transition-transform data-[state=unchecked]:translate-x-0',
          isTool ? 'data-[state=checked]:translate-x-3.5' : 'data-[state=checked]:translate-x-5',
        )}
      />
    </SwitchPrimitives.Root>
  );
});
Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
