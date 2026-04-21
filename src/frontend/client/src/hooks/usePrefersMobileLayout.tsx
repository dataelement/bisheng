import useMediaQuery from './useMediaQuery';

/**
 * Narrow viewport / H5-style shell (overlay nav, drawers, stacked regions).
 * Matches Tailwind `lg` breakpoint: max-width 1023px.
 * Use coarse-pointer / touch-only CSS (or a dedicated hook) for hover-vs-tap affordances — not this hook.
 */
export default function usePrefersMobileLayout(): boolean {
  return useMediaQuery('(max-width: 1023px)');
}
