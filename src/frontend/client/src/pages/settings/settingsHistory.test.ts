/** @jest-environment node */

import {
  createSettingsRouteState,
  readSettingsRouteState,
  resolveSettingsExitTarget,
} from "./settingsHistory";

describe("settings history", () => {
  it("captures the exact page that opened settings", () => {
    expect(
      createSettingsRouteState(
        { pathname: "/knowledge/space/42", search: "?tab=files", hash: "#recent" },
        7,
      ),
    ).toEqual({
      settingsOrigin: {
        historyIndex: 7,
        path: "/knowledge/space/42?tab=files#recent",
      },
    });
  });

  it("keeps only valid settings-owned route state", () => {
    expect(
      readSettingsRouteState({
        fromSettingsMenu: true,
        ignored: "value",
        settingsOrigin: { historyIndex: 4, path: "/c/123?mode=daily" },
      }),
    ).toEqual({
      fromSettingsMenu: true,
      settingsOrigin: { historyIndex: 4, path: "/c/123?mode=daily" },
    });

    expect(
      readSettingsRouteState({ settingsOrigin: { historyIndex: 1, path: "/settings/general" } }),
    ).toEqual({});
    expect(
      readSettingsRouteState({ settingsOrigin: { historyIndex: 1, path: "https://example.com" } }),
    ).toEqual({});
  });

  it("jumps over any settings-only entries to the source history position", () => {
    expect(
      resolveSettingsExitTarget(
        { settingsOrigin: { historyIndex: 3, path: "/knowledge" } },
        6,
      ),
    ).toEqual({ delta: -3 });
  });

  it("uses the captured path when the browser history index cannot be trusted", () => {
    expect(
      resolveSettingsExitTarget(
        { settingsOrigin: { historyIndex: null, path: "/channel/8?tab=articles" } },
        undefined,
      ),
    ).toEqual({ path: "/channel/8?tab=articles" });
  });

  it("preserves the direct-visit fallback", () => {
    expect(resolveSettingsExitTarget({}, 2)).toEqual({ delta: -1 });
    expect(resolveSettingsExitTarget({}, 0)).toEqual({ path: "/" });
  });
});
