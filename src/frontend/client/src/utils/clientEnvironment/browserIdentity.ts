import type { ClientOS, DeviceType, IdentitySource } from "./types";

interface BrowserSignals {
  userAgent?: string;
  platform?: string;
  maxTouchPoints?: number;
}

type BrowserIdentity = Readonly<{
  deviceType: DeviceType;
  os: ClientOS;
  deviceSource: IdentitySource;
  osSource: IdentitySource;
}>;

function platformOS(value: string): ClientOS {
  const platform = value.toLowerCase();
  if (platform === "windows") return "windows";
  if (platform === "macos") return "macos";
  if (platform === "linux" || platform === "chrome os") return "linux";
  if (platform === "android") return "android";
  if (platform === "ios") return "ios";
  return "unknown";
}

/** Bounded inference only: device identity is independent of width and pointer. */
export function readBrowserIdentity(signals: BrowserSignals): BrowserIdentity {
  const ua = signals.userAgent ?? "";
  const ios = /iPhone|iPad|iPod/i.test(ua);
  const android = /Android/i.test(ua);
  const mac = /Macintosh/.test(ua);
  const windows = /Windows NT/.test(ua);
  const linux = /X11.*Linux/.test(ua);
  const excluded =
    /SmartTV|Smart-TV|Android TV|GoogleTV|Tizen|Wear|Watch|Car|Automotive|TV;|TV\)/i.test(
      ua,
    );
  const mobile = /Mobile/i.test(ua);
  const tablet = /iPad|\bTablet\b/i.test(ua);
  const ambiguousMac = mac && (signals.maxTouchPoints ?? 0) > 1;
  const conflict =
    (ios && android) ||
    (windows && (ios || android || mac)) ||
    (mac && android);
  let deviceType: DeviceType = "unknown";
  if (!conflict && !excluded && !ambiguousMac) {
    if (/iPhone|iPod/i.test(ua) && !tablet) deviceType = "phone";
    else if (tablet) deviceType = "tablet";
    else if (android && mobile) deviceType = "phone";
    else if (
      android &&
      /Mozilla\/5\.0.*AppleWebKit\/.*(?:Chrome|Version)\/.*Safari\//.test(ua)
    )
      deviceType = "tablet";
    else if (!mobile && (windows || mac || linux) && /Mozilla\/5\.0/.test(ua))
      deviceType = "desktop";
  }
  let os: ClientOS = ios
    ? "ios"
    : android
      ? "android"
      : windows
        ? "windows"
        : mac
          ? "macos"
          : linux
            ? "linux"
            : "unknown";
  let osSource: IdentitySource = os === "unknown" ? "unknown" : "user-agent";
  if (conflict || ambiguousMac) {
    os = "unknown";
    osSource = "unknown";
  } else if (signals.platform) {
    const hinted = platformOS(signals.platform);
    if (hinted !== "unknown" && (os === "unknown" || hinted === os)) {
      os = hinted;
      osSource = "client-hints";
    } else {
      os = "unknown";
      osSource = "unknown";
    }
  }
  return Object.freeze({
    deviceType,
    os,
    deviceSource: deviceType === "unknown" ? "unknown" : "user-agent",
    osSource,
  });
}
