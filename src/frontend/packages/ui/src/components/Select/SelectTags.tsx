import * as React from 'react';
import { Tag } from '../Tag/Tag';
import { Tooltip } from '../Tooltip/Tooltip';
import type { SelectOption } from './types';

/** §6.2 — 4px between tags. */
const TAG_GAP = 4;

/** Room kept for the search caret after the tags while the user types (§6.3). */
const SEARCH_MIN_WIDTH = 24;

/**
 * Slack for sub-pixel layout: widths are fractional (CJK glyphs, zoom), and a
 * row that overflows by even 1px makes flexbox squeeze every tag at once.
 */
const FIT_SLACK = 2;

/** Rendered width, rounded UP — `offsetWidth` rounds to nearest and under-counts. */
function widthOf(node: Element | undefined): number {
  return node ? Math.ceil(node.getBoundingClientRect().width) : 0;
}

/**
 * §6.2 — how many tags fit on the one line the trigger has; the rest fold into
 * a `+N` tag. Measured from an invisible copy of every tag (so the answer never
 * depends on what is currently shown) and re-run when the box or the tags
 * change size. At least one tag always shows — it truncates when even that one
 * does not fit.
 */
function useVisibleCount(
  boxRef: React.RefObject<HTMLElement>,
  measureRef: React.RefObject<HTMLElement>,
  count: number,
  reserve: number,
): number {
  const [visible, setVisible] = React.useState(count);

  React.useLayoutEffect(() => {
    const box = boxRef.current;
    const measure = measureRef.current;
    if (!box || !measure) return;

    const compute = () => {
      const children = Array.from(measure.children) as HTMLElement[];
      // The last measured child is the widest possible "+N" (N = count).
      const plusWidth = widthOf(children[count]);
      // Same unit as the tag widths (rendered rect), so CSS zoom cannot skew it.
      const available = Math.floor(box.getBoundingClientRect().width) - reserve - FIT_SLACK;
      let used = 0;
      let fit = 0;
      for (let index = 0; index < count; index += 1) {
        const width = widthOf(children[index]);
        const rest = index + 1 < count ? TAG_GAP + plusWidth : 0;
        if (used + width + rest > available) break;
        used += width + TAG_GAP;
        fit = index + 1;
      }
      setVisible(Math.max(Math.min(fit, count), Math.min(1, count)));
    };

    compute();
    const observer = new ResizeObserver(compute);
    observer.observe(box);
    observer.observe(measure);
    return () => observer.disconnect();
  }, [boxRef, measureRef, count, reserve]);

  return visible;
}

export interface SelectTagsProps {
  options: SelectOption[];
  disabled: boolean;
  removeLabel?: string;
  onRemove: (option: SelectOption) => void;
  /** The search input, placed right after the tags (§6.3). */
  search?: React.ReactNode;
}

/** §6.2 — the trigger body of a multiple select: small closable tags, one line, never taller. */
export function SelectTags({ options, disabled, removeLabel, onRemove, search }: SelectTagsProps) {
  const boxRef = React.useRef<HTMLDivElement>(null);
  const measureRef = React.useRef<HTMLDivElement>(null);
  const visibleCount = useVisibleCount(
    boxRef,
    measureRef,
    options.length,
    search ? SEARCH_MIN_WIDTH + TAG_GAP : 0,
  );
  const shown = options.slice(0, visibleCount);
  const folded = options.slice(visibleCount);

  // A tag label never wraps: squeezed CJK text would otherwise break one
  // character per line. Only a lone tag that cannot fit truncates (with an
  // ellipsis), via the label span — the first child of a plain small tag.
  const renderTag = (option: SelectOption) => (
    <Tag
      size="small"
      className="max-w-full whitespace-nowrap [&>span:first-child]:truncate"
      closable={!disabled}
      disabled={disabled}
      closeLabel={removeLabel}
      onClose={() => onRemove(option)}
    >
      {option.label}
    </Tag>
  );

  return (
    <div ref={boxRef} className="relative flex min-w-0 flex-1 items-center gap-1 overflow-hidden">
      {/* Invisible measuring copy: every tag plus the widest "+N". */}
      <div
        ref={measureRef}
        aria-hidden
        className="pointer-events-none invisible absolute left-0 top-0 flex gap-1 whitespace-nowrap"
      >
        {options.map((option) => (
          <span key={option.value} className="shrink-0">
            {renderTag(option)}
          </span>
        ))}
        <span className="shrink-0">
          <Tag size="small">+{options.length}</Tag>
        </span>
      </div>

      {shown.map((option) => (
        // Only a lone tag may shrink; with several, the count above already
        // guarantees they fit, so none of them gives way.
        <span
          key={option.value}
          className={shown.length === 1 ? 'flex min-w-0 shrink' : 'flex shrink-0'}
        >
          {renderTag(option)}
        </span>
      ))}
      {folded.length > 0 && (
        // §6.2 — the fold is a default-color small tag; hovering it lists what it hides.
        <Tooltip
          content={
            <span className="flex flex-col">
              {folded.map((option) => (
                <span key={option.value}>{option.label}</span>
              ))}
            </span>
          }
        >
          <span className="flex shrink-0">
            <Tag size="small">+{folded.length}</Tag>
          </span>
        </Tooltip>
      )}
      {search}
    </div>
  );
}
