import { getClientEnvironment } from "~/utils/clientEnvironment";

/** Compatibility entry: container identity is independent of viewport width. */
export function isDesktopEmbedded(): boolean {
  return getClientEnvironment().channel === "desktop";
}
