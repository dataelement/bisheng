/**
 * A share link must survive the sidebar's auto-select.
 *
 * Opening /knowledge/share/45 left the recipient looking at their own default
 * space: the sidebar auto-selects a first space the moment its lists land, that
 * runs through the same handler as an explicit click, and the handler navigated
 * — replacing the share URL, which unmounted the preview before it could open.
 */

import { shouldNavigateOnSpaceSelect } from "./knowledgeUtils";

describe("shouldNavigateOnSpaceSelect", () => {
    it("keeps the share URL when the sidebar auto-selects another space", () => {
        expect(
            shouldNavigateOnSpaceSelect({
                isShareRoute: true,
                urlSpaceId: "45",
                targetSpaceId: "12",
            }),
        ).toBe(false);
    });

    it("keeps the share URL even when a folder id is still in the URL", () => {
        expect(
            shouldNavigateOnSpaceSelect({
                isShareRoute: true,
                urlFolderId: "88",
                urlSpaceId: "45",
                targetSpaceId: "12",
            }),
        ).toBe(false);
    });

    it("navigates when a different space is picked outside a share route", () => {
        expect(
            shouldNavigateOnSpaceSelect({
                isShareRoute: false,
                urlSpaceId: "45",
                targetSpaceId: "12",
            }),
        ).toBe(true);
    });

    it("navigates to drop a stale folder id even when the space is unchanged", () => {
        expect(
            shouldNavigateOnSpaceSelect({
                isShareRoute: false,
                urlFolderId: "88",
                urlSpaceId: "45",
                targetSpaceId: "45",
            }),
        ).toBe(true);
    });

    it("stays put when the same space is re-selected at its root", () => {
        expect(
            shouldNavigateOnSpaceSelect({
                isShareRoute: false,
                urlSpaceId: "45",
                targetSpaceId: "45",
            }),
        ).toBe(false);
    });

    it("navigates from the bare /knowledge list into the selected space", () => {
        expect(
            shouldNavigateOnSpaceSelect({
                isShareRoute: false,
                urlSpaceId: undefined,
                targetSpaceId: "12",
            }),
        ).toBe(true);
    });
});
