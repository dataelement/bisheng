import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import UserSelectedKnowledgePicker from "./UserSelectedKnowledgePicker";

const mockGetGroupedSpacesApi = jest.fn();
const mockGetSpaceChildrenApi = jest.fn();
const mockGetSpaceFolderStatsApi = jest.fn();
const mockGetWorkflowKnowledgeBasesApi = jest.fn();
const mockGetWorkflowKnowledgeFilesApi = jest.fn();

jest.mock("~/api/knowledge", () => ({
    FileType: {
        FILE: "file",
        FOLDER: "folder",
        PDF: "pdf",
    },
    getGroupedSpacesApi: (...args: unknown[]) => mockGetGroupedSpacesApi(...args),
    getSpaceChildrenApi: (...args: unknown[]) => mockGetSpaceChildrenApi(...args),
    getSpaceFolderStatsApi: (...args: unknown[]) => mockGetSpaceFolderStatsApi(...args),
    getWorkflowKnowledgeBasesApi: (...args: unknown[]) => mockGetWorkflowKnowledgeBasesApi(...args),
    getWorkflowKnowledgeFilesApi: (...args: unknown[]) => mockGetWorkflowKnowledgeFilesApi(...args),
}));

function latestSelection(onChange: jest.Mock) {
    return [...onChange.mock.calls].reverse().find(([value]) => value)?.[0];
}

function lastSelection(onChange: jest.Mock) {
    return onChange.mock.calls[onChange.mock.calls.length - 1]?.[0];
}

describe("UserSelectedKnowledgePicker", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockGetWorkflowKnowledgeBasesApi.mockResolvedValue([
            { id: "1", name: "政策知识库" },
        ]);
        mockGetWorkflowKnowledgeFilesApi.mockResolvedValue([
            { id: "101", name: "制度.pdf", fileType: 1, fileLevelPath: "", status: 2 },
        ]);
        mockGetGroupedSpacesApi.mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [
                {
                    id: "12",
                    name: "营销空间",
                    spaceLevel: "team",
                },
            ],
            personalSpaces: [],
        });
        mockGetSpaceChildrenApi.mockResolvedValue({
            data: [
                {
                    id: "2001",
                    name: "案例",
                    type: "folder",
                    status: "success",
                    visibleSuccessFileNum: 2,
                },
                {
                    id: "1001",
                    name: "话术.md",
                    type: "md",
                    status: "success",
                },
            ],
        });
        mockGetSpaceFolderStatsApi.mockResolvedValue([
            { folderId: "2001", visibleSuccessFileNum: 2 },
        ]);
    });

    it("selects a whole knowledge base into the runtime payload", async () => {
        const onChange = jest.fn();
        render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

        await screen.findByText("政策知识库");
        fireEvent.click(screen.getAllByRole("checkbox")[0]);

        await waitFor(() => {
            expect(latestSelection(onChange)).toMatchObject({
                mode: "source",
                whole_source: {
                    source_type: "knowledge",
                    source_id: 1,
                    source_name: "政策知识库",
                },
                items: [],
            });
        });
    });

    it("clears knowledge selections when switching to the space tab", async () => {
        const onChange = jest.fn();
        render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

        fireEvent.click(await screen.findByText("政策知识库"));
        fireEvent.click(await screen.findByText("制度.pdf"));

        await waitFor(() => {
            expect(latestSelection(onChange)).toMatchObject({
                mode: "items",
                items: [{ source_type: "knowledge", source_id: 1, ref_type: "file", id: 101, name: "制度.pdf" }],
            });
        });

        fireEvent.click(screen.getByRole("tab", { name: "知识空间" }));

        await waitFor(() => {
            expect(lastSelection(onChange)).toBeNull();
        });
        expect(await screen.findByText("团队空间")).toBeTruthy();

        fireEvent.click(await screen.findByText("营销空间"));
        fireEvent.click(await screen.findByText("案例"));
        fireEvent.click(await screen.findByText("话术.md"));

        await waitFor(() => {
            expect(latestSelection(onChange)).toMatchObject({
                mode: "items",
                whole_source: null,
                items: [
                    { source_type: "space", source_id: 12, ref_type: "folder", id: 2001, name: "案例" },
                    { source_type: "space", source_id: 12, ref_type: "file", id: 1001, name: "话术.md" },
                ],
                effective_file_count: 3,
            });
        });
    });

    it("reports over-limit folder scope before workflow execution", async () => {
        mockGetSpaceFolderStatsApi.mockResolvedValue([
            { folderId: "2001", visibleSuccessFileNum: 21 },
        ]);
        const onChange = jest.fn();
        render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

        fireEvent.click(screen.getByRole("tab", { name: "知识空间" }));
        fireEvent.click(await screen.findByText("营销空间"));
        fireEvent.click(await screen.findByText("案例"));

        await waitFor(() => {
            expect(latestSelection(onChange)).toMatchObject({
                mode: "items",
                items: [{ source_type: "space", source_id: 12, ref_type: "folder", id: 2001, name: "案例" }],
                effective_file_count: 21,
            });
        });
    });
});
