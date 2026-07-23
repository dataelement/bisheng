import { FileType, type KnowledgeFile } from "~/api/knowledge";
import { createTreeNode } from "../utils";
import { invalidateTargetFolderCache } from "./refreshAfterMove";

function makeFile(overrides: Partial<KnowledgeFile>): KnowledgeFile {
    return {
        id: "1",
        name: "demo",
        type: FileType.FOLDER,
        tags: [],
        path: "demo",
        spaceId: "space-1",
        createdAt: "",
        updatedAt: "",
        ...overrides,
    };
}

describe("invalidateTargetFolderCache", () => {
    it("marks root stale without mutating nested nodes when target is null", () => {
        const parent = createTreeNode(makeFile({ id: "10", name: "外层" }));
        parent.loaded = true;
        parent.children = [createTreeNode(makeFile({ id: "11", name: "内层" }))];
        const nodes = [parent];

        const result = invalidateTargetFolderCache(nodes, null);

        expect(result.rootStale).toBe(true);
        expect(result.nodes).toBe(nodes);
        expect(result.nodes[0].loaded).toBe(true);
        expect(result.nodes[0].children).toHaveLength(1);
    });

    it("clears loaded children for a nested target folder", () => {
        const innerChild = createTreeNode(makeFile({ id: "20", name: "文件A", type: FileType.PDF }));
        const target = createTreeNode(makeFile({ id: "10", name: "外层" }));
        target.loaded = true;
        target.page = 2;
        target.total = 5;
        target.hasMore = true;
        target.nextCursor = "cursor-1";
        target.children = [innerChild];

        const sibling = createTreeNode(makeFile({ id: "12", name: "其他" }));
        sibling.loaded = true;

        const result = invalidateTargetFolderCache([target, sibling], "10");

        expect(result.rootStale).toBe(false);
        expect(result.nodes[0].loaded).toBe(false);
        expect(result.nodes[0].children).toEqual([]);
        expect(result.nodes[0].page).toBe(1);
        expect(result.nodes[0].total).toBe(0);
        expect(result.nodes[0].hasMore).toBe(false);
        expect(result.nodes[0].nextCursor).toBeNull();
        // Sibling untouched
        expect(result.nodes[1].loaded).toBe(true);
    });

    it("invalidates a deeply nested target folder", () => {
        const deepTarget = createTreeNode(makeFile({ id: "30", name: "深层目标" }));
        deepTarget.loaded = true;
        deepTarget.children = [
            createTreeNode(makeFile({ id: "31", name: "旧子项", type: FileType.PDF })),
        ];

        const mid = createTreeNode(makeFile({ id: "20", name: "中层" }));
        mid.loaded = true;
        mid.children = [deepTarget];

        const root = createTreeNode(makeFile({ id: "10", name: "根下文件夹" }));
        root.loaded = true;
        root.children = [mid];

        const result = invalidateTargetFolderCache([root], "30");

        expect(result.rootStale).toBe(false);
        const invalidated = result.nodes[0].children[0].children[0];
        expect(invalidated.file.id).toBe("30");
        expect(invalidated.loaded).toBe(false);
        expect(invalidated.children).toEqual([]);
        // Ancestors remain loaded so current path browsing is not disrupted
        expect(result.nodes[0].loaded).toBe(true);
        expect(result.nodes[0].children[0].loaded).toBe(true);
    });
});
