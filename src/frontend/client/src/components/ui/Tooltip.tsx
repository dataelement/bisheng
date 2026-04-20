import * as Ariakit from '@ariakit/react';
import { AnimatePresence, motion } from 'framer-motion';
import { forwardRef, useMemo } from 'react';
import { cn } from '~/utils';

interface TooltipAnchorProps extends Ariakit.TooltipAnchorProps {
  description?: string | React.ReactNode;
  side?: 'top' | 'bottom' | 'left' | 'right';
  className?: string;
  /** When set, replaces the default dark `.tooltip` panel styles (full control). */
  tooltipClassName?: string;
  hideArrow?: boolean;
  focusable?: boolean;
  role?: string;
  showSide?: boolean;
}

export const TooltipAnchor = forwardRef<HTMLDivElement, TooltipAnchorProps>(function TooltipAnchor(
  { description, showSide, side = 'top', className, role, tooltipClassName, hideArrow = false, ...props },
  ref,
) {
  const tooltip = Ariakit.useTooltipStore({ placement: side });
  const mounted = Ariakit.useStoreState(tooltip, (state) => state.mounted);
  const placement = Ariakit.useStoreState(tooltip, (state) => state.placement);

  const { x, y } = useMemo(() => {
    const dir = placement.split('-')[0];
    switch (dir) {
      case 'top':
        return { x: 0, y: -8 };
      case 'bottom':
        return { x: 0, y: 8 };
      case 'left':
        return { x: -8, y: 0 };
      case 'right':
        return { x: 8, y: 0 };
      default:
        return { x: 0, y: 0 };
    }
  }, [placement]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (role === 'button' && event.key === 'Enter') {
      event.preventDefault();
      (event.target as HTMLDivElement).click();
    }
  };

  return (
    <Ariakit.TooltipProvider store={tooltip} hideTimeout={0}>
      <Ariakit.TooltipAnchor
        {...props}
        ref={ref}
        role={role}
        onKeyDown={handleKeyDown}
        className={cn('cursor-pointer', className)}
      />
      {!showSide && (
        <AnimatePresence>
          {mounted === true && (
            <Ariakit.Tooltip
              gutter={4}
              alwaysVisible
              className={cn(tooltipClassName || 'tooltip')}
              render={
                <motion.div
                  initial={{ opacity: 0, x, y }}
                  animate={{ opacity: 1, x: 0, y: 0 }}
                  exit={{ opacity: 0, x, y }}
                />
              }
            >
              {!hideArrow && <Ariakit.TooltipArrow />}
              {tooltipClassName ? description : <span className="text-sm">{description}</span>}
            </Ariakit.Tooltip>
          )}
        </AnimatePresence>
      )
      }
    </Ariakit.TooltipProvider>
  );
});
