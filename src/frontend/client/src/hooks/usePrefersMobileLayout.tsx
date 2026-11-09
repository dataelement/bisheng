import { useClientLayout } from "./useClientEnvironment";

/**
 * Narrow viewport / H5-style shell (overlay nav, drawers, stacked regions).
 * Standalone web uses this shell below 768px; DSH keeps the desktop shell.
 * Use coarse-pointer / touch-only CSS (or a dedicated hook) for hover-vs-tap affordances — not this hook.
 */
export default function usePrefersMobileLayout(): boolean {
  return useClientLayout().prefersMobileLayout;
}
