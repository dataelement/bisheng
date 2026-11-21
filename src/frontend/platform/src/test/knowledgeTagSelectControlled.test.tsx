import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useState } from "react";
import KnowledgeTagSelect from "@/pages/KnowledgePage/components/tags/KnowledgeTagSelect";

const mocks = vi.hoisted(() => ({ get: vi.fn(), save: vi.fn(), error: vi.fn(), create: vi.fn(), remove: vi.fn() }));
vi.mock("@/controllers/API/knowledgeTags", () => ({
  getKnowledgeTagsApi: mocks.get,
  setFileTagsApi: mocks.save,
  batchAddFileTagsApi: vi.fn(),
  createKnowledgeTagApi: mocks.create,
  deleteKnowledgeTagApi: mocks.remove,
}));
vi.mock("@/controllers/request", () => ({ showApiError: mocks.error }));
const tags = [{ id: 4, name: "Finance" }, { id: 5, name: "Legal" }];
const updated = vi.fn();
function ControlledEditor() {
  const [open, setOpen] = useState(true);
  return <KnowledgeTagSelect knowledgeId={7} fileIds={[11]} initialTags={[tags[0]]}
    open={open} onOpenChange={setOpen} onUpdate={updated} />;
}
beforeEach(() => {
  vi.clearAllMocks();
  mocks.get.mockResolvedValue({ data: tags, total: 2 });
  mocks.save.mockResolvedValue({});
});
afterEach(cleanup);

it("saves a single file's complete selection and closes the externally opened editor", async () => {
  render(<ControlledEditor />);
  fireEvent.click(await screen.findByText("Legal"));
  fireEvent.click(screen.getByRole("button", { name: "bs:confirmButton" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({ knowledge_id: 7, file_id: 11, tag_ids: [4, 5] }, false));
  expect(updated).toHaveBeenCalledOnce();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

it("retains the editor and draft after a failed save", async () => {
  mocks.save.mockRejectedValue(new Error("save failed"));
  render(<ControlledEditor />);
  fireEvent.click(await screen.findByText("Legal"));
  fireEvent.click(screen.getByRole("button", { name: "bs:confirmButton" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalledOnce());
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(updated).not.toHaveBeenCalled();
  mocks.save.mockResolvedValue({});
  fireEvent.click(screen.getByRole("button", { name: "bs:confirmButton" }));
  await waitFor(() => expect(mocks.save).toHaveBeenLastCalledWith({ knowledge_id: 7, file_id: 11, tag_ids: [4, 5] }, false));
});


it("uses space tag APIs for a knowledge-space file", async () => {
 render(<KnowledgeTagSelect isSpace knowledgeId={7} fileIds={[11]} initialTags={[tags[0]]} open onUpdate={updated} />);
 fireEvent.click(await screen.findByText("Legal"));
 expect(mocks.get).toHaveBeenCalledWith(7, {page: 1, limit: 100}, true);
 fireEvent.click(screen.getByRole("button", {name: "bs:confirmButton"}));
 await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({knowledge_id: 7, file_id: 11, tag_ids: [4, 5]}, true));
});


it("keeps existing file tags editable while space tag creation and deletion are restricted", async () => {
  render(<KnowledgeTagSelect isSpace knowledgeId={7} fileIds={[11]} initialTags={[tags[0]]}
    spaceTagPermission={{ status: "restricted", retry: vi.fn() }} open onUpdate={updated} />);
  expect(await screen.findByText("tagEditor.spacePermissionRequired")).toBeVisible();
  expect(screen.getByRole("textbox")).toBeDisabled();
  fireEvent.keyDown(screen.getByRole("textbox"), { key: "Enter" });
  const remove = screen.getAllByRole("button", { name: "tagEditor.deleteTag" });
  expect(remove.every(button => button.hasAttribute("disabled"))).toBe(true);
  fireEvent.click(remove[0]);
  fireEvent.click(screen.getByText("Legal"));
  fireEvent.click(screen.getByRole("button", { name: "bs:confirmButton" }));
  await waitFor(() => expect(mocks.save).toHaveBeenCalledWith({ knowledge_id: 7, file_id: 11, tag_ids: [4, 5] }, true));
  expect(mocks.create).not.toHaveBeenCalled();
  expect(mocks.remove).not.toHaveBeenCalled();
});
