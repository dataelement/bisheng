import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditTagsModal } from "./EditTagsModal";
import { addSpaceTagApi, getSpaceTagsApi } from "~/api/knowledge";
const mockOpen = jest.fn(),
  mockClose = jest.fn();
jest.mock("../hooks/useKnowledgeBatch", () => ({
  useKnowledgeBatch: () => ({ view: null, open: mockOpen, close: mockClose }),
}));
jest.mock("~/api/knowledge", () => ({
  getSpaceTagsApi: jest.fn(),
  addSpaceTagApi: jest.fn(),
  updateFileTagsApi: jest.fn(),
  deleteSpaceTagApi: jest.fn(),
}));
jest.mock("~/api/request", () => ({ showApiError: jest.fn() }));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("~/utils", () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(" "),
  getFullWidthLength: (value: string) => value.length,
}));
jest.mock("~/components/ui", () => ({
  ...jest.requireActual("~/components/ui/dialog"),
  ...jest.requireActual("~/components/ui/button"),
}));
function mount() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <EditTagsModal
        isOpen
        spaceId="3"
        fileIds={["7", "8"]}
        batchItems={[
          { id: 7, type: "file", name: "visible.txt" },
          { id: 8, type: "folder", name: "folder" },
        ]}
        availableTags={[{ id: 11, name: "known" }]}
        onClose={mockClose}
      />
    </QueryClientProvider>,
  );
}
it("stages names locally and cancels with zero Tag or Root-visible dictionary IO", async () => {
  mount();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "draft" } });
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  await screen.findByRole("button", { name: "draft ×" });
  expect(addSpaceTagApi).not.toHaveBeenCalled();
  expect(getSpaceTagsApi).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "com_knowledge.cancel" }));
  expect(mockOpen).not.toHaveBeenCalled();
});
it("passes the complete typed selection and local draft only to confirmation review", async () => {
  mockOpen.mockResolvedValue(null);
  mount();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "draft" } });
  fireEvent.click(screen.getByRole("button", { name: "com_knowledge.confirm" }));
  await waitFor(() =>
    expect(mockOpen).toHaveBeenCalledWith(
      expect.objectContaining({
        operation: "tag",
        items: [
          { id: 7, type: "file", name: "visible.txt" },
          { id: 8, type: "folder", name: "folder" },
        ],
        new_tag_names: ["draft"],
      }),
    ),
  );
  expect(addSpaceTagApi).not.toHaveBeenCalled();
  expect(mockClose).not.toHaveBeenCalled();
});
