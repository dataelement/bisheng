import { FileType, type KnowledgeFile } from "~/api/knowledge";
import { fileEncodingCategoryLabel } from "./uploadMetadata";
import {
    buildPortalDocumentPath,
    createTreeNode,
    dedupeFilesById,
    dedupeTreeNodesByFileId,
    extractExt,
    mergeRootTreeNodesPreservingLoadedFolders,
    normalizePortalFileCategoryGroups,
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

    describe("mergeRootTreeNodesPreservingLoadedFolders", () => {
        it("keeps loaded folder children when the folder also appears in the root listing", () => {
            const child = createTreeNode(makeFile({ id: "201", name: "child.md", type: FileType.MD }));
            const loadedFolder = {
                ...createTreeNode(makeFile({ id: "101", name: "folder" })),
                children: [child],
                expanded: true,
                loaded: true,
                total: 1,
            };
            const rootFolder = makeFile({ id: "101", name: "folder (root meta)" });
            const sibling = makeFile({ id: "102", name: "other.md", type: FileType.MD });

            const merged = mergeRootTreeNodesPreservingLoadedFolders(
                [loadedFolder],
                [rootFolder, sibling],
                "101",
            );

            expect(merged).toHaveLength(2);
            expect(merged[0].file.name).toBe("folder (root meta)");
            expect(merged[0].loaded).toBe(true);
            expect(merged[0].children).toEqual([child]);
            expect(merged[1].file.id).toBe("102");
        });

        it("keeps the current folder node when it is missing from the root page", () => {
            const child = createTreeNode(makeFile({ id: "201", name: "child.md", type: FileType.MD }));
            const deepFolder = {
                ...createTreeNode(makeFile({ id: "101", name: "deep" })),
                children: [child],
                loaded: true,
            };
            const rootFile = makeFile({ id: "102", name: "root.md", type: FileType.MD });

            const merged = mergeRootTreeNodesPreservingLoadedFolders(
                [deepFolder],
                [rootFile],
                "101",
            );

            expect(merged.map((node) => node.file.id)).toEqual(["101", "102"]);
            expect(merged[0].children).toEqual([child]);
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

        it("keeps first-level categories for file encoding options", () => {
            expect(
                normalizePortalFileCategoryOptions([
                    {
                        code: "POL",
                        label: "政策制度",
                        children: [
                            { code: "POL-REG", label: "制度文件" },
                            { code: "POL-NOTICE", label: "通知公告" },
                        ],
                    },
                    { code: "RPT", label: "报告" },
                ]),
            ).toEqual([
                { code: "POL", label: "政策制度" },
                { code: "RPT", label: "报告" },
            ]);
        });

        it("builds upload category groups with selectable second-level children", () => {
            expect(
                normalizePortalFileCategoryGroups([
                    {
                        code: "POL",
                        label: "政策制度",
                        children: [
                            { code: "POL_REG", label: "制度文件" },
                            { code: "POL_NOTICE", label: "通知公告" },
                        ],
                    },
                ]),
            ).toEqual([
                {
                    code: "POL",
                    label: "政策制度",
                    children: [
                        {
                            code: "POL_REG",
                            label: "制度文件",
                            parentCode: "POL",
                            parentLabel: "政策制度",
                            displayLabel: "政策制度 / 制度文件",
                        },
                        {
                            code: "POL_NOTICE",
                            label: "通知公告",
                            parentCode: "POL",
                            parentLabel: "政策制度",
                            displayLabel: "政策制度 / 通知公告",
                        },
                    ],
                },
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

    describe("buildPortalDocumentPath", () => {
        it("includes folder path from search result metadata when previewing a file", () => {
            expect(buildPortalDocumentPath({
                activeGroupTitle: "个人知识库",
                activeSpaceName: "我的技术文档",
                selectedFile: makeFile({
                    id: "401",
                    name: "搜索结果.md",
                    type: FileType.MD,
                    folderPath: "我的技术文档/制度文件",
                    sourcePath: "我的技术文档>制度文件/搜索结果.md",
                }),
            })).toBe("全部知识库/个人知识库/我的技术文档/制度文件");
        });

        it("falls back to current folder breadcrumbs when metadata is missing", () => {
            expect(buildPortalDocumentPath({
                activeGroupTitle: "个人知识库",
                activeSpaceName: "我的技术文档",
                currentPath: [{ name: "制度文件" }],
                selectedFile: makeFile({
                    id: "401",
                    name: "搜索结果.md",
                    type: FileType.MD,
                }),
            })).toBe("全部知识库/个人知识库/我的技术文档/制度文件");
        });
    });
});
