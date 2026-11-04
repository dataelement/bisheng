import { readDesktopPresentation } from "./presentation";
export { readDesktopPresentation } from "./presentation";
import { readBrowserIdentity } from "./browserIdentity";
import { parseHostInfo } from "./hostInfo";
import type { ClientEnvironment, IdentitySource } from "./types";

export type {
  ClientChannel,
  ClientEnvironment,
  ClientOS,
  DeviceType,
  DesktopHostInfo,
} from "./types";
export const DESKTOP_SESSION_KEY = "dsh:embedded-chat";

const fallback: ClientEnvironment = Object.freeze({
  channel: "web",
  deviceType: "unknown",
  os: "unknown",
  sources: Object.freeze({
    channel: "default",
    deviceType: "unknown",
    os: "unknown",
  }),
  capabilities: Object.freeze({ hasNativePresentation: false }),
});
let snapshot = fallback;
const listeners = new Set<() => void>();

function readSession(): boolean {
  try {
    return window.sessionStorage.getItem(DESKTOP_SESSION_KEY) === "true";
  } catch {
    return false;
  }
}

/** Explicitly sampled at entry and by the router; reads remain stable for React. */
export function refreshClientEnvironment(): ClientEnvironment {
  if (typeof window === "undefined") return fallback;
  let presentation: Window["dshChatPresentation"];
  try {
    presentation = window.dshChatPresentation;
  } catch {
    /* Missing preload access. */
  }
  let host: ReturnType<typeof parseHostInfo>;
  let hasNativePresentation = false;
  try {
    host = parseHostInfo(presentation?.hostInfo);
  } catch {
    /* A malformed bridge cannot block the app. */
  }
  hasNativePresentation =
    typeof readDesktopPresentation().reportLanding === "function";
  const requested =
    new URLSearchParams(window.location.search).get("embed") === "dsh";
  const remembered = readSession();
  const channelSource: IdentitySource = host
    ? "host"
    : hasNativePresentation
      ? "legacy-bridge"
      : requested
        ? "entry"
        : remembered
          ? "session"
          : snapshot.channel === "desktop"
            ? snapshot.sources.channel
            : "default";
  const channel = channelSource === "default" ? "web" : "desktop";
  if (channel === "desktop" && !remembered) {
    try {
      window.sessionStorage.setItem(DESKTOP_SESSION_KEY, "true");
    } catch {
      /* Memory survives SPA navigation. */
    }
  }
  let signals = {};
  try {
    const navigator = window.navigator as Navigator & {
      userAgentData?: { platform?: string };
    };
    signals = {
      userAgent: navigator?.userAgent,
      maxTouchPoints: navigator?.maxTouchPoints,
      platform: navigator?.userAgentData?.platform,
    };
  } catch {
    /* Unknown devices retain all generic functionality. */
  }
  const browser = readBrowserIdentity(signals);
  const next: ClientEnvironment = Object.freeze({
    channel,
    deviceType: host?.deviceType ?? browser.deviceType,
    os: host?.os ?? (channel === "desktop" ? "unknown" : browser.os),
    sources: Object.freeze({
      channel: channelSource,
      deviceType: host ? "host" : browser.deviceSource,
      os: host ? "host" : channel === "desktop" ? "unknown" : browser.osSource,
    }),
    capabilities: Object.freeze({ hasNativePresentation }),
  });
  if (typeof document !== "undefined")
    document.documentElement.dataset.bishengSurface = channel;
  if (JSON.stringify(next) !== JSON.stringify(snapshot)) {
    snapshot = next;
    [...listeners].forEach((listener) => listener());
  }
  return snapshot;
}

export function getClientEnvironment(): ClientEnvironment {
  return typeof window === "undefined" ? fallback : snapshot;
}

export function subscribeClientEnvironment(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

refreshClientEnvironment();
