import useMediaQuery from './useMediaQuery';

/**
 * Primary input is a mouse-like pointer that can hover.
 *
 * Mirrors the `fine-pointer` / `coarse-pointer` Tailwind variants (same media
 * query), for the cases CSS alone cannot cover — picking a different *component*
 * per input type, e.g. a hover Tooltip on desktop vs a tap-to-open Popover on
 * touch. Note that `hoverOnlyWhenSupported` already strips `hover:` styles on
 * touch, so plain styling never needs this hook.
 *
 * Not a viewport check: a touch panel can be wide and a desktop window narrow.
 * For layout breakpoints use `usePrefersMobileLayout`.
 */
export default function useFinePointer(): boolean {
  return useMediaQuery('(hover: hover) and (pointer: fine)');
}
