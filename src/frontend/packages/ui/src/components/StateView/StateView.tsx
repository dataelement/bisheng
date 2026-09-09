import * as React from 'react';
import cn from '../../utils/cn';

/**
 * StateView — the shell for "this area has no normal content to show"
 * (组件-State状态页.md; the design language calls it 状态页 / State, the code
 * export is StateView so it never reads as a React state variable).
 *
 * One component covers both halves of the spec: an area with nothing in it
 * (§2.1 empty / no results / no permission / cleared) and an area reporting
 * what just happened (§2.2 success / 404 / 500). They share ONE layout — the
 * scenario group changes what you write, never how it is typeset (§4) — so the
 * only knob is `size`, i.e. how big the container is (§3).
 *
 * Presentation-only per the library contract: every string arrives as a prop,
 * the artwork arrives as a node, the buttons arrive as a node.
 */

export type StateViewSize = 'page' | 'panel' | 'inline';

interface StateViewBaseProps {
  /** 主提示: the state itself. Required — a state page always says what state it is. */
  title: React.ReactNode;
  /**
   * 辅助说明: why, or what to do next. Carries the optional text link (§4.2).
   * Its presence is what promotes `title` to a real title (§4.1) — a lone line
   * is not a heading, it is one sentence of copy, and is typeset as such.
   */
  description?: React.ReactNode;
  className?: string;
}

interface StateViewFramedProps extends StateViewBaseProps {
  size?: 'page' | 'panel';
  /** The illustration element, e.g. `<EmptyStateIllustration />`. Sized here, never by the caller. */
  image?: React.ReactNode;
  /** At most one primary + one secondary Button, primary LAST (§5). More exits go in `description` as links. */
  action?: React.ReactNode;
}

interface StateViewInlineProps extends StateViewBaseProps {
  size: 'inline';
  /**
   * A table row or a dropdown gets one line and nothing else (§3). `image` /
   * `action` are `never` on purpose: the spec's "ignored at runtime" rule is
   * stronger as a compile error, and this package has no dev-only warning
   * channel (strict TS, no node types).
   */
  image?: never;
  action?: never;
}

export type StateViewProps = StateViewFramedProps | StateViewInlineProps;

/** §3: art size follows the container, and the phone drops the page tier to the panel tier (§7). */
const IMAGE_SIZE: Record<'page' | 'panel', string> = {
  page: 'size-[120px] max-md:size-20',
  panel: 'size-20',
};

/** §6: the area must not collapse or stretch when its content turns into a state page. */
const MIN_HEIGHT: Record<'page' | 'panel', string> = {
  page: 'min-h-[320px]',
  panel: 'min-h-[200px]',
};

/** §4.1: 16px between blocks, 4px inside one. Same three numbers for every scenario and tier. */
const GAP_BLOCK = 'mb-4';
const GAP_INSIDE = 'mb-1';

export function StateView(props: StateViewProps) {
  const { size = 'page', title, description, className } = props;

  if (size === 'inline') {
    // One centered line, no art, no button (§3): the containers this tier serves
    // are too short for art to breathe and too small for a button to be hit.
    return (
      <div
        className={cn(
          'flex w-full items-center justify-center px-4 py-3 text-center text-body text-text-3',
          className,
        )}
      >
        {title}
      </div>
    );
  }

  const { image, action } = props;

  // §4.1: the deciding question is "is this line a title at all?" — with copy
  // under it, yes (16/24, 500, text-1); standing alone it was never a heading,
  // just one sentence, and shouting it in 16/500 makes "this is empty for now"
  // louder than the real content around it.
  const titleClass = description ? 'text-h4 text-text-1' : 'text-body text-text-3';

  return (
    // §6: plain flex centering, both axes — one mechanism, no offset math. In
    // the few containers that are far taller than their content (or that have a
    // floating dock over the bottom edge), the caller nudges the block up with
    // an asymmetric padding through `className` (`pb-16`, `pb-[112px]` …);
    // twMerge keeps it, and centering resolves inside the remaining box.
    <div
      className={cn(
        'flex h-full w-full flex-col items-center justify-center px-4',
        MIN_HEIGHT[size],
        className,
      )}
    >
      {/* §4: content block centered, capped at 400px — a wider line of text
          makes the eye sweep back and forth and stops reading as one unit. */}
      <div className="flex w-full max-w-[400px] flex-col items-center text-center">
        {image ? (
          // §8: the art is decoration — every word of information lives in the
          // text, so screen readers skip it entirely.
          <span aria-hidden className={cn('block shrink-0 [&>svg]:size-full', GAP_BLOCK, IMAGE_SIZE[size])}>
            {image}
          </span>
        ) : null}

        <p className={cn(titleClass, description ? GAP_INSIDE : action ? GAP_BLOCK : undefined)}>
          {title}
        </p>

        {description ? (
          <p className={cn('text-body text-text-3', action ? GAP_BLOCK : undefined)}>{description}</p>
        ) : null}

        {action ? (
          // §5: side by side, 8px apart, PRIMARY LAST (rightmost) — callers pass
          // them in reading order, secondary then primary. On phones they stack
          // full-width with the primary on TOP (§7), which is the reverse of the
          // desktop order, hence flex-col-reverse: business code keeps writing
          // one order and both layouts come out right.
          <div className="flex items-center justify-center gap-2 max-md:w-full max-md:flex-col-reverse max-md:gap-3 max-md:[&>*]:w-full">
            {action}
          </div>
        ) : null}
      </div>
    </div>
  );
}
