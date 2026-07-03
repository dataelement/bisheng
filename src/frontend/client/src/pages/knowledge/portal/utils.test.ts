import { FileType, type KnowledgeFile } from "~/api/knowledge";
import { fileEncodingCategoryLabel } from "./uploadMetadata";
import {
    createTreeNode,
    dedupeFilesById,
    dedupeTreeNodesByFileId,
    extractExt,
    normalizePortalFileCategoryOptions,
} from "./utils";

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

describe("portal preview utils", () => {
    describe("extractExt", () => {
        it("prefers the preview URL extension for web link titles without an extension", () => {
            expect(
                extractExt(
                    "首钢股份知库 – 钢铁行业知识共享平台",
                    "http://localhost:9000/bisheng/preview/74.md?X-Amz-Signature=abc",
                ),
            ).toBe("md");
        });

        it("uses the preview URL extension for media transcript previews", () => {
            expect(
                extractExt(
                    "乔布斯_副本.m4a",
                    "http://localhost:9000/bisheng/preview/88.md",
                ),
            ).toBe("md");
        });

        it("does not treat an extensionless display name as a file type", () => {
            expect(extractExt("首钢股份知库 – 钢铁行业知识共享平台")).toBe("txt");
        });

        it("falls back to the display name extension when no preview URL is available", () => {
            expect(extractExt("VCU告警操作文档.docx")).toBe("docx");
        });
    });

    describe("folder list dedupe", () => {
        it("keeps the first row for duplicate file ids", () => {
            const created = makeFile({ id: "101", name: "BBB" });
            const duplicate = makeFile({ id: "101", name: "BBB duplicate" });
            const sibling = makeFile({ id: "102", name: "AAA" });

            expect(dedupeFilesById([created, duplicate, sibling])).toEqual([created, sibling]);
        });

        it("dedupes tree nodes within each folder level", () => {
            const child = createTreeNode(makeFile({ id: "201", name: "child" }));
            const duplicateChild = createTreeNode(makeFile({ id: "201", name: "child duplicate" }));
            const parent = {
                ...createTreeNode(makeFile({ id: "101", name: "parent" })),
                children: [child, duplicateChild],
            };
            const duplicateParent = createTreeNode(makeFile({ id: "101", name: "parent duplicate" }));
            const sibling = createTreeNode(makeFile({ id: "102", name: "sibling" }));

            expect(dedupeTreeNodesByFileId([parent, duplicateParent, sibling])).toEqual([
                {
                    ...parent,
                    children: [child],
                },
                sibling,
            ]);
        });
    });

    describe("file category options", () => {
        it("removes hidden characters before matching file encoding codes", () => {
            expect(
                normalizePortalFileCategoryOptions([
                    { code: "STD\u200B", label: "标准规范\u200B" },
                    { code: "\uFEFFcas", label: "\u200C案例" },
                    { code: "CAS", label: "重复案例" },
                ]),
            ).toEqual([
                { code: "STD", label: "标准规范" },
                { code: "CAS", label: "案例" },
            ]);
        });

        it("matches category labels against normalized option codes", () => {
            expect(
                fileEncodingCategoryLabel("CAS", [
                    { code: "CAS\u200B", label: "案例\u200B" },
                ]),
            ).toBe("CAS / 案例");
        });
    });
});
