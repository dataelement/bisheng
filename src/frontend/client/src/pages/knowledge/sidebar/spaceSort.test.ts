import { KnowledgeSpace, SpaceLevel, SpaceSortType } from "~/api/knowledge";
import { applyPinOrderToSpaceList, sortKnowledgeSpacesForSection } from "./spaceSort";

function space(
    id: string,
    overrides: Partial<KnowledgeSpace> = {},
): KnowledgeSpace {
    return {
        id,
        name: id,
        description: "",
        icon: "",
        visibility: "private" as KnowledgeSpace["visibility"],
        isReleased: true,
        isPinned: false,
        spaceLevel: SpaceLevel.PUBLIC,
        updatedAt: "2026-01-01T00:00:00Z",
        ...overrides,
    };
}

describe("sortKnowledgeSpacesForSection", () => {
    it("keeps relative order among pinned spaces", () => {
        const input = [
            space("b", { isPinned: true, name: "B", updatedAt: "2026-01-02T00:00:00Z" }),
            space("a", { isPinned: true, name: "A", updatedAt: "2026-01-03T00:00:00Z" }),
            space("c", { isPinned: false, name: "C" }),
        ];

        const byName = sortKnowledgeSpacesForSection(input, SpaceSortType.NAME);
        expect(byName.map((item) => item.id)).toEqual(["b", "a", "c"]);

        const byTime = sortKnowledgeSpacesForSection(input, SpaceSortType.UPDATE_TIME);
        expect(byTime.map((item) => item.id)).toEqual(["b", "a", "c"]);
    });

    it("still floats pinned spaces above unpinned ones", () => {
        const input = [
            space("c", { isPinned: false, name: "C" }),
            space("a", { isPinned: true, name: "A" }),
            space("b", { isPinned: false, name: "B" }),
        ];

        expect(
            sortKnowledgeSpacesForSection(input, SpaceSortType.NAME).map((item) => item.id),
        ).toEqual(["a", "b", "c"]);
    });
});

describe("applyPinOrderToSpaceList", () => {
    it("moves a newly pinned space to the front", () => {
        const input = [
            space("a", { isPinned: true }),
            space("b", { isPinned: false }),
            space("c", { isPinned: false }),
        ];

        expect(applyPinOrderToSpaceList(input, "c", true).map((item) => item.id)).toEqual([
            "c",
            "a",
            "b",
        ]);
        expect(applyPinOrderToSpaceList(input, "c", true)[0].isPinned).toBe(true);
    });

    it("places an unpinned space after the remaining pinned block", () => {
        const input = [
            space("b", { isPinned: true }),
            space("a", { isPinned: true }),
            space("c", { isPinned: false }),
        ];

        expect(applyPinOrderToSpaceList(input, "a", false).map((item) => item.id)).toEqual([
            "b",
            "a",
            "c",
        ]);
        expect(applyPinOrderToSpaceList(input, "a", false).find((item) => item.id === "a")?.isPinned).toBe(
            false,
        );
    });
});
