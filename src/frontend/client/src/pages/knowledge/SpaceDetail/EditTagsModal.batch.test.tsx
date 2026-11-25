import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditTagsModal } from "./EditTagsModal";
import { addSpaceTagApi, deleteSpaceTagApi, getSpaceTagsApi } from "~/api/knowledge";
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
function mount(canManageSpaceTags = true, canReadSpaceTags = false) {
  const client = new QueryClient();
  const content = (spaceId = "3") => <QueryClientProvider client={client}>
      <EditTagsModal
        tagScope={{ kind: 'native', key: 'member' }}
        canManageSpaceTags={canManageSpaceTags}
        canReadSpaceTags={canReadSpaceTags}
        isOpen
        spaceId={spaceId}
        fileIds={["7", "8"]}
        batchItems={[
          { id: 7, type: "file", name: "visible.txt" },
          { id: 8, type: "folder", name: "folder" },
        ]}
        availableTags={[{ id: 11, name: "known" }]}
        onClose={mockClose}
      />
    </QueryClientProvider>;
  const view = render(content());
  return { updateSpace: (spaceId: string) => view.rerender(content(spaceId)) };
}
beforeEach(() => {
  jest.mocked(getSpaceTagsApi).mockResolvedValue([{ id: 12, name: "Space tag" }]);
});
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


it("explains restricted space actions while allowing existing file tag assignments", async () => {
  mockOpen.mockResolvedValue(null);
  mount(false);
  expect(screen.getByText("com_knowledge.tag_permissions.space_required")).toBeVisible();
  expect(screen.getByRole("textbox")).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "new" } });
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  expect(addSpaceTagApi).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "" } });
  fireEvent.click(screen.getByText("known"));
  const remove = screen.getByTitle("com_knowledge.tag_permissions.space_required");
  expect(remove).toBeDisabled();
  fireEvent.click(remove);
  expect(deleteSpaceTagApi).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "com_knowledge.confirm" }));
  await waitFor(() => expect(mockOpen).toHaveBeenCalledWith(expect.objectContaining({ tag_ids: [11], new_tag_names: [] })));
});

it("loads and assigns a space tag absent from selected files with root view permission only", async () => {
  mockOpen.mockResolvedValue(null);
  mount(false, true);
  fireEvent.click(await screen.findByText("Space tag"));
  expect(getSpaceTagsApi).toHaveBeenCalledWith("3");
  expect(screen.getByRole("textbox")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "com_knowledge.confirm" }));
  await waitFor(() => expect(mockOpen).toHaveBeenCalledWith(expect.objectContaining({ tag_ids: [12], new_tag_names: [] })));
  expect(addSpaceTagApi).not.toHaveBeenCalled();
});

it("retries failed space tag loading and preserves the selection", async () => {
  jest.mocked(getSpaceTagsApi).mockRejectedValueOnce(new Error("unavailable"));
  mount(false, true);
  await screen.findByText("com_knowledge.batch.tags_load_failed");
  fireEvent.click(screen.getByText("known"));
  fireEvent.click(screen.getByRole("button", { name: "com_ui_retry" }));
  await screen.findByText("Space tag");
  expect(screen.getAllByText("known")).toHaveLength(2);
  expect(screen.getByRole("textbox")).toBeDisabled();
});

it("discards old space candidates that finish loading after navigation", async () => {
  let resolve!: (tags: { id: number; name: string }[]) => void;
  jest.mocked(getSpaceTagsApi).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  const view = mount(false, true);
  view.updateSpace("4");
  await screen.findByText("Space tag");
  await act(async () => { resolve([{ id: 19, name: "Old space" }]); });
  expect(screen.queryByText("Old space")).not.toBeInTheDocument();
});
