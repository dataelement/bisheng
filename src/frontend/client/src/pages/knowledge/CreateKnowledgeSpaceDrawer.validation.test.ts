import { describe, expect, it } from "@jest/globals";
import { selectedAutoTagLibrariesHaveTags } from "./CreateKnowledgeSpaceDrawer";

describe("selectedAutoTagLibrariesHaveTags", () => {
    it("returns false when no libraries are selected", () => {
        expect(selectedAutoTagLibrariesHaveTags([], [{ id: 1, name: "A", tag_count: 3, is_builtin: false }], [])).toBe(false);
    });

    it("returns true when merged tag names exist", () => {
        expect(selectedAutoTagLibrariesHaveTags([1], [{ id: 1, name: "A", tag_count: 0, is_builtin: false }], ["设备"])).toBe(true);
    });

    it("returns false when all selected libraries have zero tags", () => {
        expect(
            selectedAutoTagLibrariesHaveTags(
                [1, 2],
                [
                    { id: 1, name: "Empty A", tag_count: 0, is_builtin: false },
                    { id: 2, name: "Empty B", tag_count: 0, is_builtin: false },
                ],
                [],
            ),
        ).toBe(false);
    });

    it("returns true when any selected library has tags", () => {
        expect(
            selectedAutoTagLibrariesHaveTags(
                [1, 2],
                [
                    { id: 1, name: "Empty", tag_count: 0, is_builtin: false },
                    { id: 2, name: "Has tags", tag_count: 4, is_builtin: false },
                ],
                [],
            ),
        ).toBe(true);
    });
});
