import { portalScopeFileCountLabel, resolvePortalScopeFileCount } from "./scopeFileCount";

const space = { id: "9", name: "制度库" };

describe("resolvePortalScopeFileCount", () => {
    it("uses the open document when a file is selected", () => {
        expect(resolvePortalScopeFileCount({
            space,
            folder: { id: "3", name: "目录", fileNum: 4 },
            file: { name: "说明.pdf" },
        })).toEqual({ kind: "file", name: "说明.pdf", count: 0 });
    });

    it("uses the open folder count when no file is selected", () => {
        expect(resolvePortalScopeFileCount({
            space,
            folder: { id: "3", name: "目录", fileNum: 4 },
            file: null,
        })).toEqual({ kind: "folder", name: "目录", folderId: "3", count: 4 });
    });

    it("keeps the folder count pending until stats arrive", () => {
        expect(resolvePortalScopeFileCount({
            space,
            folder: { id: "3", name: "目录" },
            file: null,
        })?.count).toBeNull();
    });

    it("falls back to the knowledge space", () => {
        expect(resolvePortalScopeFileCount({
            space,
            folder: null,
            file: null,
        })).toEqual({ kind: "space", name: "制度库", spaceId: "9", count: null });
    });
});

describe("portalScopeFileCountLabel", () => {
    it("names the scope and the file total", () => {
        expect(portalScopeFileCountLabel("space", 12)).toBe("当前知识库下 12 个文件");
        expect(portalScopeFileCountLabel("folder", 3)).toBe("当前文件夹下 3 个文件");
        expect(portalScopeFileCountLabel("file", 0)).toBe("所选文件下 0 个文件");
        expect(portalScopeFileCountLabel("space", null)).toBe("当前知识库下文件数统计中");
    });
});
