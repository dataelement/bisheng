import type { KnowledgeSpace } from "~/api/knowledge";

import { resolveReorderNeighbours } from "./SpaceSidebar";

/** Sidebar order: pinned spaces are floated to the top, so a,b sit above c,d,e. */
const space = (id: string, isPinned = false) => ({ id, name: id, isPinned } as KnowledgeSpace);
const SPACES = [space("a", true), space("b", true), space("c"), space("d"), space("e")];

describe("resolveReorderNeighbours", () => {
    it("anchors a non-pinned row to the pinned boundary without using a pinned neighbour", () => {
        // Dropping e just under the pinned block: b must not become the neighbour, or the
        // backend averages two unrelated weights and e snaps back where it was.
        expect(resolveReorderNeighbours(SPACES, "e", "c", "before")).toEqual({
            prevSpaceId: null,
            nextSpaceId: "c",
        });
    });

    it("anchors between two non-pinned rows", () => {
        expect(resolveReorderNeighbours(SPACES, "e", "c", "after")).toEqual({
            prevSpaceId: "c",
            nextSpaceId: "d",
        });
    });

    it("anchors to the end of the non-pinned block", () => {
        expect(resolveReorderNeighbours(SPACES, "c", "e", "after")).toEqual({
            prevSpaceId: "e",
            nextSpaceId: null,
        });
    });

    it("reorders within the pinned block using pinned neighbours only", () => {
        expect(resolveReorderNeighbours(SPACES, "b", "a", "before")).toEqual({
            prevSpaceId: null,
            nextSpaceId: "a",
        });
    });

    it("clamps a non-pinned row dropped inside the pinned block to the top of its own group", () => {
        // The row can't outrank pinned spaces, so it lands first among the non-pinned.
        expect(resolveReorderNeighbours(SPACES, "e", "a", "after")).toEqual({
            prevSpaceId: null,
            nextSpaceId: "c",
        });
    });

    it("returns null when the row is dropped on itself or the target is unknown", () => {
        expect(resolveReorderNeighbours(SPACES, "e", "e", "before")).toBeNull();
        expect(resolveReorderNeighbours(SPACES, "e", "zz", "before")).toBeNull();
    });

    it("reports no anchor when the row is alone in its pin group", () => {
        const spaces = [space("a", true), space("b", true), space("c")];
        expect(resolveReorderNeighbours(spaces, "c", "a", "after")).toEqual({
            prevSpaceId: null,
            nextSpaceId: null,
        });
    });
});
