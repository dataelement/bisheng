/**
 * Report the browser's IANA timezone to the memory module once per change
 * (F132 decision 13). One call site covers daily chat, app chat and deep
 * research: the backend copies the reported value onto each chat's
 * registration, so chat requests themselves carry no timezone.
 */
import { useEffect } from "react";
import { reportMemoryTimezoneApi } from "~/api/memory";

/** Per-user key: a shared browser must not suppress another account's report. */
export function timezoneStorageKey(userId: string): string {
  return `bs:memory-timezone:${userId}`;
}

export function readBrowserTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

function readLastReported(key: string): string | null {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeLastReported(key: string, value: string): void {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* storage disabled — the next load reports again, which is harmless */
  }
}

/** Returns true when a report was sent and accepted. */
export async function reportTimezoneIfChanged(userId: string | null | undefined): Promise<boolean> {
  if (!userId) return false;
  const timezone = readBrowserTimezone();
  if (!timezone) return false;
  const key = timezoneStorageKey(userId);
  if (readLastReported(key) === timezone) return false;
  try {
    await reportMemoryTimezoneApi(timezone);
  } catch {
    // Keep the old value so the next load retries.
    return false;
  }
  writeLastReported(key, timezone);
  return true;
}

/** Mount once in the signed-in shell. */
export function useMemoryTimezone(userId: string | null | undefined): void {
  useEffect(() => {
    if (!userId) return;
    void reportTimezoneIfChanged(userId);
  }, [userId]);
}
