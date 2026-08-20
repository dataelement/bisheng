import { render, screen } from "@testing-library/react";

import { PortalInfoDrawer } from "./PortalInfoDrawer";

function renderSourceDrawer(entryType?: "normal" | "manager" | "publish" | "share") {
    render(
        <PortalInfoDrawer
            activePanel="source"
            activeSpace={{ id: "20", name: "当前知识库" } as any}
            selectedFile={{
                id: "100",
                name: "制度.pdf",
                type: "pdf",
                tags: [],
                path: "",
                spaceId: "20",
                createdAt: "",
                updatedAt: "",
                entryType,
                originalUploaderName: "最初上传人张三",
                originalKnowledgeName: "最初个人知识库",
            } as any}
            documentPath="/制度.pdf"
            fileCategoryGroups={[]}
            businessDomainOptions={[]}
            encodingPrefix=""
            onClose={jest.fn()}
            onCopyShareLink={jest.fn()}
            onPanelChange={jest.fn()}
        />,
    );
}

describe("PortalInfoDrawer original origin", () => {
    it.each(["manager", "publish", "share"] as const)(
        "shows original origin for a %s entry",
        (entryType) => {
            renderSourceDrawer(entryType);

            expect(screen.getByText("原始上传人")).toBeInTheDocument();
            expect(screen.getByText("最初上传人张三")).toBeInTheDocument();
            expect(screen.getByText("原始上传知识库")).toBeInTheDocument();
            expect(screen.getByText("最初个人知识库")).toBeInTheDocument();
        },
    );

    it("does not add original origin rows for an ordinary file", () => {
        renderSourceDrawer("normal");

        expect(screen.queryByText("原始上传人")).not.toBeInTheDocument();
        expect(screen.queryByText("原始上传知识库")).not.toBeInTheDocument();
    });

    it("shows local upload ingest method by default", () => {
        renderSourceDrawer("normal");

        expect(screen.getByText("入库方式")).toBeInTheDocument();
        expect(screen.getByText("本地上传")).toBeInTheDocument();
    });

    it("shows api sync ingest method when filelib metadata is present", () => {
        render(
            <PortalInfoDrawer
                activePanel="source"
                activeSpace={{ id: "20", name: "当前知识库" } as any}
                selectedFile={{
                    id: "100",
                    name: "制度.pdf",
                    type: "pdf",
                    tags: [],
                    path: "",
                    spaceId: "20",
                    createdAt: "",
                    updatedAt: "",
                    userMetadata: {
                        filelib_sync_endpoint: "inspection_standard_sync",
                        external_file_id: "INSPECTION-STD-DEPT-A-abc",
                    },
                } as any}
                documentPath="/制度.pdf"
                fileCategoryGroups={[]}
                businessDomainOptions={[]}
                encodingPrefix=""
                onClose={jest.fn()}
                onCopyShareLink={jest.fn()}
                onPanelChange={jest.fn()}
            />,
        );

        expect(screen.getByText("入库方式")).toBeInTheDocument();
        expect(screen.getByText("接口同步")).toBeInTheDocument();
    });
});

describe("PortalInfoDrawer version number", () => {
    it("formats the primary version number as a single decimal", () => {
        render(
            <PortalInfoDrawer
                activePanel="properties"
                activeSpace={{ id: "20", name: "当前知识库" } as any}
                selectedFile={{
                    id: "100",
                    name: "制度.pdf",
                    type: "pdf",
                    tags: [],
                    path: "",
                    spaceId: "20",
                    createdAt: "",
                    updatedAt: "",
                    version_no: 3,
                } as any}
                documentPath="/制度.pdf"
                fileCategoryGroups={[]}
                businessDomainOptions={[]}
                encodingPrefix=""
                onClose={jest.fn()}
                onCopyShareLink={jest.fn()}
                onPanelChange={jest.fn()}
            />,
        );

        expect(screen.getByText("版本号")).toBeInTheDocument();
        expect(screen.getByText("3.0")).toBeInTheDocument();
    });
});
