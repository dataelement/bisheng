/**
 * Leaving space settings resumes the location the user entered from.
 *
 * Save / cancel used to land on the settings' own space root, dropping the
 * folder the user was working in (and switching spaces when the settings were
 * opened for another space from the sidebar).
 */

import { SETTINGS_RETURN_STATE_KEY, resolveSettingsReturnPath } from "./knowledgeUtils";

const fallback = "/knowledge/space/7";

describe("resolveSettingsReturnPath", () => {
    it("returns to the recorded space folder", () => {
        const state = { [SETTINGS_RETURN_STATE_KEY]: "/knowledge/space/3/folder/42" };
        expect(resolveSettingsReturnPath(state, fallback)).toBe("/knowledge/space/3/folder/42");
    });

    it("keeps the query string of the recorded location", () => {
        const state = { [SETTINGS_RETURN_STATE_KEY]: "/knowledge?square=1" };
        expect(resolveSettingsReturnPath(state, fallback)).toBe("/knowledge?square=1");
    });

    it("falls back when opened by a direct link", () => {
        expect(resolveSettingsReturnPath(null, fallback)).toBe(fallback);
        expect(resolveSettingsReturnPath(undefined, fallback)).toBe(fallback);
        expect(resolveSettingsReturnPath({}, fallback)).toBe(fallback);
    });

    it("ignores anything that is not an in-app knowledge path", () => {
        for (const returnTo of ["https://evil.example", "//evil.example", "/c/new", "/knowledgeX", 42]) {
            expect(resolveSettingsReturnPath({ [SETTINGS_RETURN_STATE_KEY]: returnTo }, fallback)).toBe(fallback);
        }
    });
});
