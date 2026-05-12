import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import * as API from "@/controllers/API";
import { KnowledgeTree } from "./KnowledgeTree";

vi.mock("@/controllers/API", () => ({
    listKnowledgeChildren: vi.fn(),
}));

const mockedList = vi.mocked(API.listKnowledgeChildren);

const rootFolders: API.KnowledgeNode[] = [
    { id: 1, file_name: "项目A", file_type: 0, file_size: null, created_at: "", updated_at: "" },
    { id: 2, file_name: "项目B", file_type: 0, file_size: null, created_at: "", updated_at: "" },
];
const subFolders: API.KnowledgeNode[] = [
    { id: 11, file_name: "文档", file_type: 0, file_size: null, created_at: "", updated_at: "" },
];

describe("KnowledgeTree", () => {
    beforeEach(() => {
        mockedList.mockReset();
    });

    it("renders root folders fetched on mount", async () => {
        mockedList.mockResolvedValueOnce({ items: rootFolders, total: 2 });

        render(<KnowledgeTree knowledgeId={5} onSelectFolder={() => {}} />);

        await waitFor(() => {
            expect(screen.getByText("项目A")).toBeInTheDocument();
            expect(screen.getByText("项目B")).toBeInTheDocument();
        });
        // Should fetch with file_type=0 (DIR only) and parent_id=null
        expect(mockedList).toHaveBeenCalledWith({
            knowledge_id: 5,
            parent_id: null,
            file_type: 0,
        });
    });

    it("expand arrow click lazy-loads children", async () => {
        mockedList
            .mockResolvedValueOnce({ items: rootFolders, total: 2 })
            .mockResolvedValueOnce({ items: subFolders, total: 1 });

        render(<KnowledgeTree knowledgeId={5} onSelectFolder={() => {}} />);
        await waitFor(() => screen.getByText("项目A"));

        fireEvent.click(screen.getByTestId("tree-expand-1"));
        await waitFor(() => {
            expect(screen.getByText("文档")).toBeInTheDocument();
        });
        expect(mockedList).toHaveBeenLastCalledWith({
            knowledge_id: 5,
            parent_id: 1,
            file_type: 0,
        });
    });

    it("click on folder name fires onSelectFolder with id+name", async () => {
        mockedList.mockResolvedValueOnce({ items: rootFolders, total: 2 });
        const onSel = vi.fn();
        render(<KnowledgeTree knowledgeId={5} onSelectFolder={onSel} />);
        await waitFor(() => screen.getByText("项目A"));

        fireEvent.click(screen.getByText("项目A"));
        expect(onSel).toHaveBeenCalledWith({ id: 1, name: "项目A" });
    });

    it("expand on empty folder shows nothing extra (optimistic arrow)", async () => {
        mockedList
            .mockResolvedValueOnce({ items: rootFolders, total: 2 })
            .mockResolvedValueOnce({ items: [], total: 0 });
        render(<KnowledgeTree knowledgeId={5} onSelectFolder={() => {}} />);
        await waitFor(() => screen.getByText("项目A"));

        fireEvent.click(screen.getByTestId("tree-expand-1"));
        await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2));
        // No children rendered
        expect(screen.queryByText("文档")).not.toBeInTheDocument();
    });
});
