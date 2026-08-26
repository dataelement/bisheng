import type { Location } from "react-router-dom";

export interface SettingsOrigin {
  historyIndex: number | null;
  path: string;
}

export interface SettingsRouteState {
  fromSettingsMenu?: true;
  settingsOrigin?: SettingsOrigin;
}

export type SettingsExitTarget =
  | { delta: number; path?: never }
  | { delta?: never; path: string };

type SourceLocation = Pick<Location, "hash" | "pathname" | "search">;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSafeOriginPath(path: unknown): path is string {
  return (
    typeof path === "string" &&
    path.startsWith("/") &&
    !path.startsWith("//") &&
    !/^\/settings(?:[/?#]|$)/.test(path)
  );
}

function readHistoryIndex(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0 ? value : null;
}

/** Capture the route that opened settings once; settings navigation must only carry it forward. */
export function createSettingsRouteState(
  location: SourceLocation,
  historyIndex: unknown,
): SettingsRouteState {
  return {
    settingsOrigin: {
      historyIndex: readHistoryIndex(historyIndex),
      path: `${location.pathname}${location.search}${location.hash}`,
    },
  };
}

/** Read only the state owned by the settings route and discard malformed deep-link state. */
export function readSettingsRouteState(value: unknown): SettingsRouteState {
  if (!isRecord(value)) return {};

  const state: SettingsRouteState = {};
  if (value.fromSettingsMenu === true) state.fromSettingsMenu = true;

  if (isRecord(value.settingsOrigin) && isSafeOriginPath(value.settingsOrigin.path)) {
    state.settingsOrigin = {
      historyIndex: readHistoryIndex(value.settingsOrigin.historyIndex),
      path: value.settingsOrigin.path,
    };
  }

  return state;
}

/**
 * Prefer returning to the exact source history entry so its in-memory route state survives.
 * The saved path is the deterministic fallback if browser history was replaced or reloaded.
 */
export function resolveSettingsExitTarget(
  state: SettingsRouteState,
  currentHistoryIndex: unknown,
): SettingsExitTarget {
  const currentIndex = readHistoryIndex(currentHistoryIndex);
  const origin = state.settingsOrigin;

  if (origin) {
    if (
      origin.historyIndex !== null &&
      currentIndex !== null &&
      currentIndex > origin.historyIndex
    ) {
      return { delta: origin.historyIndex - currentIndex };
    }
    return { path: origin.path };
  }

  return currentIndex !== null && currentIndex > 0 ? { delta: -1 } : { path: "/" };
}
