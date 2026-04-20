import useMediaQuery from './useMediaQuery';

/**
 * Whether to use touch-first / H5 shell (overlay nav, drawers, stacked regions).
 * True when the primary interaction is not "desktop-like" (mouse + hover-capable fine pointer).
 * Does not use viewport width — resizing the window does not switch shell mode on PC.
 */
export default function usePrefersMobileLayout(): boolean {
  const isDesktopLikePointer = useMediaQuery('(hover: hover) and (pointer: fine)');
  return !isDesktopLikePointer;
}
