import { FileType, type KnowledgeFile } from "~/api/knowledge";

import { resolveFolderReorderNeighbours } from "./resolveFolderReorderNeighbours";

const folder = (id: string) => ({ id, name: id, type: FileType.FOLDER } as KnowledgeFile);
const file = (id: string) => ({ id, name: id, type: FileType.PDF } as KnowledgeFile);

/** The list renders folders first, then files. */
const ROWS = [folder("a"), folder("b"), folder("c"), file("f1"), file("f2")];

describe("resolveFolderReorderNeighbours", () => {
    it("anchors between two folders", () => {
        expect(resolveFolderReorderNeighbours(ROWS, "c", "a", "after")).toEqual({
            prevFolderId: "a",
            nextFolderId: "b",
        });
    });

    it("anchors to the top of the folder block", () => {
        expect(resolveFolderReorderNeighbours(ROWS, "c", "a", "before")).toEqual({
            prevFolderId: null,
            nextFolderId: "a",
        });
    });

    it("anchors to the end of the folder block, never against a file", () => {
        // Dropping after the last folder must not pick up f1 as the next neighbour.
        expect(resolveFolderReorderNeighbours(ROWS, "a", "c", "after")).toEqual({
            prevFolderId: "c",
            nextFolderId: null,
        });
    });

    it("refuses a file as the drop target", () => {
        expect(resolveFolderReorderNeighbours(ROWS, "a", "f1", "before")).toBeNull();
    });

    it("refuses dropping a row on itself or an unknown target", () => {
        expect(resolveFolderReorderNeighbours(ROWS, "a", "a", "before")).toBeNull();
        expect(resolveFolderReorderNeighbours(ROWS, "a", "zz", "before")).toBeNull();
    });

    it("ignores the placeholder row of a folder being created", () => {
        const rows = [folder("a"), { ...folder("tmp"), isCreating: true } as KnowledgeFile, folder("b")];
        expect(resolveFolderReorderNeighbours(rows, "b", "a", "after")).toEqual({
            prevFolderId: "a",
            nextFolderId: null,
        });
    });

    it("reports no anchor when it is the only folder", () => {
        const rows = [folder("a"), file("f1")];
        expect(resolveFolderReorderNeighbours(rows, "a", "f1", "before")).toBeNull();
    });
});
