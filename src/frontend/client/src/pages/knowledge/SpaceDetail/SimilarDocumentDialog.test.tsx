import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { SimilarDocumentDialog } from "./SimilarDocumentDialog";

const mockPending = [{ knowledge_file_id: 120, file_name: "来源文件", candidate_count: 1, can_associate: false }];
const mockCandidates = [{ target_document_id: 10, title: "相似发布文件", current_primary_version_no: 1,
    similarity: 0.95, primary_knowledge_file_id: 110, content_file_id: 10, can_associate: false }];
const mockEmpty: unknown[] = [];
const mockMutate = jest.fn();

jest.mock("@tanstack/react-query", () => ({
    useQuery: ({ queryKey }: any) => ({ data: queryKey[0] === "pending-similar" ? mockPending : queryKey[0] === "similar-candidates" ? mockCandidates : mockEmpty, isLoading: false }),
    useMutation: () => ({ mutate: mockMutate, isPending: false }),
    useQueryClient: () => ({ invalidateQueries: jest.fn() }),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/hooks/Input", () => ({ useDebounce: (value: string) => value }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: jest.fn() }), useConfirm: () => jest.fn() }));
jest.mock("~/api/knowledge", () => ({}));
jest.mock("~/components/ui/Dialog", () => ({
    Dialog: ({ open, children }: any) => open ? <div>{children}</div> : null,
    DialogContent: ({ children }: any) => <div>{children}</div>,
    DialogHeader: ({ children }: any) => <div>{children}</div>,
    DialogTitle: ({ children }: any) => <h2>{children}</h2>,
}));
jest.mock("~/components/ui/Tooltip2", () => ({
    Tooltip: ({ children }: any) => <div>{children}</div>,
    TooltipTrigger: ({ children }: any) => <div>{children}</div>,
    TooltipContent: () => null,
}));
jest.mock("./VersionComparePreviewDialog", () => ({
    VersionComparePreviewDialog: ({ open, spaceId, left, right }: any) => open
        ? <div data-testid="preview">{spaceId}:{left.fileId}:{right.fileId}</div> : null,
}));

test("相似发布入口能在目标库预览且不展示版本关联操作", async () => {
    render(<SimilarDocumentDialog open spaceId={3} onOpenChange={jest.fn()} />);
    expect(await screen.findByText("相似发布文件")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "com_knowledge.version.btn_link_as_new_version" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "com_knowledge.version.btn_view" }));
    expect(screen.getByTestId("preview")).toHaveTextContent("3:120:110");
    expect(mockMutate).not.toHaveBeenCalled();
});
