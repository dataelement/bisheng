import type { DesktopHostInfo } from "./types";

/** Treat metadata as an untrusted presentation hint, never as authorization. */
export function parseHostInfo(value: unknown): DesktopHostInfo | undefined {
  if (!value || typeof value !== "object" || Array.isArray(value))
    return undefined;
  try {
    const info = value as Record<string, unknown>;
    if (
      info.protocolVersion !== 1 ||
      info.channel !== "desktop" ||
      info.deviceType !== "desktop"
    )
      return undefined;
    const os =
      info.os === "windows" || info.os === "macos" || info.os === "linux"
        ? info.os
        : "unknown";
    return Object.freeze({
      protocolVersion: 1,
      channel: "desktop",
      deviceType: "desktop",
      os,
    });
  } catch {
    return undefined;
  }
}
