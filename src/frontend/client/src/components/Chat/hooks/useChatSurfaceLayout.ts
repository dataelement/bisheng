import type { RefObject } from "react";
import { useElementSize } from "~/hooks/useElementSize";

/** The combined chat/panel region stays stable when a panel docks inside it. */
export function useChatSurfaceLayout(ref: RefObject<HTMLDivElement>) {
  const { width } = useElementSize(ref);
  return { contentWidth: width, isCompactLayout: width === 0 || width <= 1023 };
}
