import useMediaQuery from './useMediaQuery';
import { isDesktopEmbedded } from '~/components/Chat/desktopEmbedding';

/**
 * Narrow viewport / H5-style shell (overlay nav, drawers, stacked regions).
 * Breakpoint: width < 768px.
 * Use coarse-pointer / touch-only CSS (or a dedicated hook) for hover-vs-tap affordances — not this hook.
 */
export default function usePrefersMobileLayout(): boolean {
  const narrowViewport = useMediaQuery('(max-width: 767px)');
  // The host owns navigation; its content pane keeps the desktop page layout.
  return isDesktopEmbedded() ? false : narrowViewport;
}
