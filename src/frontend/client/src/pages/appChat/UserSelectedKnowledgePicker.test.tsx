import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import UserSelectedKnowledgePicker from "./UserSelectedKnowledgePicker";

const mockGetGroupedSpacesApi = jest.fn();
const mockGetSpaceChildrenApi = jest.fn();
const mockGetSpaceFolderStatsApi = jest.fn();

jest.mock("~/api/knowledge", () => ({
    FileType: {
        FILE: "file",
        FOLDER: "folder",
        PDF: "pdf",
    },
    getGroupedSpacesApi: (...args: unknown[]) => mockGetGroupedSpacesApi(...args),
    getSpaceChildrenApi: (...args: unknown[]) => mockGetSpaceChildrenApi(...args),
    getSpaceFolderStatsApi: (...args: unknown[]) => mockGetSpaceFolderStatsApi(...args),
}));

function latestSelection(onChange: jest.Mock) {
    return [...onChange.mock.calls].reverse().find(([value]) => value)?.[0];
}

describe("UserSelectedKnowledgePicker", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockGetGroupedSpacesApi.mockResolvedValue({
            publicSpaces: [],
            departmentSpaces: [],
            teamSpaces: [
                {
                    id: "12",
                    name: "营销空间",
                    spaceLevel: "team",
                },
                {
                    id: "13",
                    name: "运营空间",
                    spaceLevel: "team",
                },
            ],
            personalSpaces: [],
        });
        mockGetSpaceChildrenApi.mockImplementation(({ space_id }) => {
            if (String(space_id) === "13") {
                return Promise.resolve({
                    data: [
                        {
                            id: "3001",
                            name: "复盘.md",
                            type: "md",
                            status: "success",
                        },
                    ],
                });
            }
            return Promise.resolve({
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
        });
        mockGetSpaceFolderStatsApi.mockResolvedValue([
            { folderId: "2001", visibleSuccessFileNum: 2 },
        ]);
    });

    it("selects a whole knowledge space into the runtime payload", async () => {
        const onChange = jest.fn();
        render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

        await screen.findByText("营销空间");
        expect(screen.queryByRole("tab", { name: "文档知识库" })).not.toBeInTheDocument();
        fireEvent.click(screen.getAllByRole("checkbox")[0]);

        await waitFor(() => {
            expect(latestSelection(onChange)).toMatchObject({
                mode: "source",
                whole_source: {
                    source_type: "space",
                    source_id: 12,
                    source_name: "营销空间",
                },
                items: [],
            });
        });
    });

    it("keeps file and folder scope inside one selected knowledge space", async () => {
        const onChange = jest.fn();
        render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

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

    it("clears previous scope when selecting files from another knowledge space", async () => {
        const onChange = jest.fn();
        render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

        fireEvent.click(await screen.findByText("营销空间"));
        fireEvent.click(await screen.findByText("话术.md"));
        fireEvent.click(await screen.findByText("运营空间"));
        fireEvent.click(await screen.findByText("复盘.md"));

        await waitFor(() => {
            expect(latestSelection(onChange)).toMatchObject({
                mode: "items",
                whole_source: null,
                items: [
                    { source_type: "space", source_id: 13, ref_type: "file", id: 3001, name: "复盘.md" },
                ],
                effective_file_count: 1,
            });
        });
    });

    it("reports over-limit folder scope before workflow execution", async () => {
        mockGetSpaceFolderStatsApi.mockResolvedValue([
            { folderId: "2001", visibleSuccessFileNum: 21 },
        ]);
        const onChange = jest.fn();
        render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

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
