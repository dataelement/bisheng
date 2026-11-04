import { useSyncExternalStore } from "react";
import {
  getClientEnvironment,
  subscribeClientEnvironment,
} from "~/utils/clientEnvironment";
import useFinePointer from "./useFinePointer";
import useMediaQuery from "./useMediaQuery";

/** Container, space, input and device facts deliberately remain separate. */
export function useClientEnvironment() {
  const identity = useSyncExternalStore(
    subscribeClientEnvironment,
    getClientEnvironment,
    getClientEnvironment,
  );
  const isNarrowViewport = useMediaQuery("(max-width: 767px)");
  const isCompactViewport = useMediaQuery("(max-width: 1023px)");
  const prefersHoverInteraction = useFinePointer();
  let hasTouchInput = false;
  try {
    hasTouchInput =
      typeof navigator !== "undefined" && navigator.maxTouchPoints > 0;
  } catch {
    /* Unknown capability. */
  }
  return {
    ...identity,
    layout: { isNarrowViewport, isCompactViewport },
    input: { prefersHoverInteraction, hasTouchInput },
  } as const;
}
