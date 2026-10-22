import * as React from 'react';
import cn from '../../utils/cn';
import type { InputSize } from '../Input/shared';
import { InputNumber } from '../InputNumber/InputNumber';
import { Tooltip } from '../Tooltip/Tooltip';

interface QuickJumperProps {
  size: InputSize;
  totalPages: number;
  disabled?: boolean;
  prefix: React.ReactNode;
  suffix: React.ReactNode;
  /** Tooltip shown while the typed page is out of range. */
  errorText: string;
  /** Accessible name of the box. */
  ariaLabel?: string;
  onJump: (page: number) => void;
}

/**
 * §5.3 — the box fits a 3-digit page next to InputNumber's reserved 20px
 * stepper column at every size.
 */
const BOX_WIDTH: Record<InputSize, string> = {
  small: 'w-16',
  medium: 'w-[72px]',
  large: 'w-20',
};

/**
 * 「跳至 [ ] 页」 (§5.3), on InputNumber: a page is a number, so the box gets
 * the 1…N range, integer-only input, ↑ / ↓ stepping and the "never rewrite
 * what the user typed" rule for free. Submits on Enter or blur and empties
 * itself after a jump. Out of range does NOT jump and is NOT corrected to the
 * last page — the box turns red and explains the range on hover. The range
 * goes in a tooltip rather than InputNumber's hint line, which would break
 * the one-row pager.
 */
export function QuickJumper({
  size,
  totalPages,
  disabled,
  prefix,
  suffix,
  errorText,
  ariaLabel,
  onJump,
}: QuickJumperProps) {
  const [page, setPage] = React.useState<number | null>(null);
  const [invalid, setInvalid] = React.useState(false);

  const handleSubmit = () => {
    if (page === null) {
      setInvalid(false);
      return;
    }
    if (!Number.isInteger(page) || page < 1 || page > totalPages) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    setPage(null);
    onJump(page);
  };

  return (
    <span
      className={cn(
        'flex shrink-0 items-center gap-2 whitespace-nowrap text-text-2',
        disabled && 'text-text-4',
      )}
    >
      {prefix}
      <Tooltip content={errorText} disabled={!invalid}>
        <InputNumber
          size={size}
          status={invalid ? 'error' : 'default'}
          className={BOX_WIDTH[size]}
          inputClassName="text-center tabular-nums"
          min={1}
          max={totalPages}
          precision={0}
          aria-label={ariaLabel}
          disabled={disabled}
          value={page}
          onChange={(next) => {
            setPage(next);
            // Editing is the correction; the red shell would only nag now.
            setInvalid(false);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter') handleSubmit();
          }}
          onBlur={handleSubmit}
        />
      </Tooltip>
      {suffix}
    </span>
  );
}
