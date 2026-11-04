import type { DesktopPresentation } from "./types";

type MethodName = Exclude<keyof DesktopPresentation, "hostInfo">;

/** Missing or non-callable legacy methods must not break generic host rendering. */
export function readDesktopPresentation(): DesktopPresentation {
  let bridge: DesktopPresentation | undefined;
  try {
    if (typeof window !== "undefined") bridge = window.dshChatPresentation;
  } catch {
    /* No preload access. */
  }
  function method<K extends MethodName>(key: K): DesktopPresentation[K] {
    try {
      const candidate = bridge?.[key];
      return (
        typeof candidate === "function" ? candidate.bind(bridge) : undefined
      ) as DesktopPresentation[K];
    } catch {
      return undefined;
    }
  }
  return Object.freeze({
    reportLanding: method("reportLanding"),
    reportKnowledgeDialog: method("reportKnowledgeDialog"),
    reportNavigation: method("reportNavigation"),
    reportSettings: method("reportSettings"),
    requestSettingsClose: method("requestSettingsClose"),
    requestSettingsFocus: method("requestSettingsFocus"),
  });
}
