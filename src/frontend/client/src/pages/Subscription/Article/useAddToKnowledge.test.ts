import { act, renderHook, waitFor } from "@testing-library/react";

import { addArticleToKnowledgeApi, createFolderApi } from "~/api/knowledge";
import type { AddToKnowledgeModalProps } from "./AddToKnowledgeModal";
import { useAddToKnowledge } from "./useAddToKnowledge";

jest.mock("~/api/knowledge", () => ({
  getManagedSpacesApi: jest.fn(),
  getMineSpacesApi: jest.fn(),
  getSpaceChildrenApi: jest.fn(),
  createFolderApi: jest.fn(),
  addArticleToKnowledgeApi: jest.fn(),
  FileType: { DIR: 0, FILE: 1 },
}));
jest.mock("~/hooks", () => ({ useScrollRevealRef: () => ({ current: null }) }));
jest.mock("~/hooks/useMediaQuery", () => ({ __esModule: true, default: () => false }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("~/common", () => ({ NotificationSeverity: { WARNING: "warning" } }));
jest.mock("~/utils", () => ({
  generateUUID: () => "folder-code",
  getFullWidthLength: (value: string) => value.length,
}));
jest.mock("~/components/icons/channels", () => ({ ChannelNotebookOneIcon: () => null }));

type CreatedFolder = Awaited<ReturnType<typeof createFolderApi>>;
type Mode = NonNullable<AddToKnowledgeModalProps["mode"]>;

beforeEach(() => {
  jest.mocked(createFolderApi).mockReset();
  jest.mocked(addArticleToKnowledgeApi).mockReset();
});

function folder(id: string, name = "Saved folder"): CreatedFolder {
  return { id, name } as CreatedFolder;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

async function picker(mode: Mode = "channel_sync") {
  const onSyncSelect = jest.fn();
  const onOpenChange = jest.fn();
  const showToast = jest.fn();
  const props: AddToKnowledgeModalProps = {
    open: true,
    onOpenChange,
    onSyncSelect,
    mode,
    articleId: "article-1",
    dataSourceApi: jest.fn().mockResolvedValue([{ id: "10", name: "Space" }]),
  };
  const hook = renderHook(
    ({ open }) => useAddToKnowledge({ ...props, open }, (key) => key, showToast),
    { initialProps: { open: true } },
  );
  await waitFor(() => expect(hook.result.current.displayTree[0]?.id).toBe("10"));
  return { ...hook, onSyncSelect, onOpenChange, showToast };
}

type Picker = Awaited<ReturnType<typeof picker>>;

async function addDraft(value: Picker, parent = "10", level = 1) {
  await act(async () => value.result.current.handleAddFolder(parent, level, "10"));
  const id = value.result.current.selectedId;
  if (!id) throw new Error("Expected a newly selected folder draft");
  return id;
}

it.each<Mode>(["channel_sync", "article"])(
  "does not confirm an uncreated folder in %s mode",
  async (mode) => {
    const value = await picker(mode);
    await addDraft(value);
    expect(value.result.current.canConfirm).toBe(false);
    await act(async () => value.result.current.handleConfirm());
    expect(createFolderApi).not.toHaveBeenCalled();
    expect(value.onSyncSelect).not.toHaveBeenCalled();
    expect(addArticleToKnowledgeApi).not.toHaveBeenCalled();
  },
);

it("deduplicates Enter/blur saves and confirms only the persisted folder ID", async () => {
  const pending = deferred<CreatedFolder>();
  jest.mocked(createFolderApi).mockReturnValueOnce(pending.promise);
  const value = await picker();
  const id = await addDraft(value);
  let saving!: Promise<void>;
  act(() => { saving = value.result.current.handleSaveEdit(id, "Saved folder"); });
  await act(async () => value.result.current.handleSaveEdit(id, "Saved folder"));
  expect(createFolderApi).toHaveBeenCalledTimes(1);
  expect(value.result.current.isCreatingFolder).toBe(true);
  expect(value.result.current.canConfirm).toBe(false);
  await act(async () => value.result.current.handleConfirm());
  expect(value.onSyncSelect).not.toHaveBeenCalled();
  await act(async () => { pending.resolve(folder("100")); await saving; });
  expect(value.result.current.isCreatingFolder).toBe(false);
  expect(value.result.current.canConfirm).toBe(true);
  await act(async () => value.result.current.handleConfirm());
  expect(value.onSyncSelect).toHaveBeenCalledWith({
    knowledgeSpaceId: "10", knowledgeSpaceName: "Space",
    folderId: "100", folderPath: "Saved folder",
  });
});

it("clears the selection when creation fails and cannot confirm the removed draft", async () => {
  jest.mocked(createFolderApi).mockRejectedValueOnce(new Error("creation failed"));
  const value = await picker();
  const id = await addDraft(value);
  await act(async () => value.result.current.handleSaveEdit(id, "Saved folder"));
  expect(value.result.current.selectedId).toBeNull();
  expect(value.result.current.editingId).toBeNull();
  expect(value.result.current.isCreatingFolder).toBe(false);
  expect(value.result.current.canConfirm).toBe(false);
  expect(value.result.current.displayTree[0].children).toEqual([]);
  expect(value.showToast).toHaveBeenCalledTimes(1);
  await act(async () => value.result.current.handleConfirm());
  expect(value.onSyncSelect).not.toHaveBeenCalled();
});

it("ignores an old response after reopen even when both drafts have the same timestamp ID", async () => {
  jest.spyOn(Date, "now").mockReturnValue(1730000000000);
  const first = deferred<CreatedFolder>();
  const second = deferred<CreatedFolder>();
  jest.mocked(createFolderApi).mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
  const value = await picker();
  const id = await addDraft(value);
  let oldSave!: Promise<void>;
  act(() => { oldSave = value.result.current.handleSaveEdit(id, "Old folder"); });
  act(() => value.result.current.handleOpenChange(false));
  value.rerender({ open: false });
  value.rerender({ open: true });
  await waitFor(() => expect(value.result.current.displayTree[0]?.id).toBe("10"));
  const newId = await addDraft(value);
  expect(newId).toBe(id);
  let newSave!: Promise<void>;
  act(() => { newSave = value.result.current.handleSaveEdit(newId, "New folder"); });
  await act(async () => { first.resolve(folder("100", "Old folder")); await oldSave; });
  expect(value.result.current.selectedId).toBe(newId);
  expect(value.result.current.isCreatingFolder).toBe(true);
  expect(value.result.current.canConfirm).toBe(false);
  await act(async () => { second.resolve(folder("200", "New folder")); await newSave; });
  expect(value.result.current.selectedId).toBe("200");
  expect(value.result.current.canConfirm).toBe(true);
});

it("uses the real persisted parent when creating a nested folder", async () => {
  jest.mocked(createFolderApi).mockResolvedValueOnce(folder("100", "Parent"))
    .mockResolvedValueOnce(folder("200", "Child"));
  const value = await picker();
  const parent = await addDraft(value);
  await act(async () => value.result.current.handleSaveEdit(parent, "Parent"));
  const child = await addDraft(value, "100", 2);
  await act(async () => value.result.current.handleSaveEdit(child, "Child"));
  expect(createFolderApi).toHaveBeenNthCalledWith(2, "10", { name: "Child", parent_id: "100" });
  await act(async () => value.result.current.handleConfirm());
  expect(value.onSyncSelect).toHaveBeenCalledWith(expect.objectContaining({ folderId: "200", folderPath: "Parent/Child" }));
});

it("still confirms an existing space without creating a folder", async () => {
  const value = await picker();
  act(() => value.result.current.handleSelect("10"));
  expect(value.result.current.canConfirm).toBe(true);
  await act(async () => value.result.current.handleConfirm());
  expect(value.onSyncSelect).toHaveBeenCalledWith(expect.objectContaining({ folderId: null }));
  expect(createFolderApi).not.toHaveBeenCalled();
});

it("uploads an article only under the real created folder", async () => {
  jest.mocked(createFolderApi).mockResolvedValueOnce(folder("100"));
  const value = await picker("article");
  const id = await addDraft(value);
  await act(async () => value.result.current.handleSaveEdit(id, "Saved folder"));
  await act(async () => value.result.current.handleConfirm());
  expect(addArticleToKnowledgeApi).toHaveBeenCalledWith("10", ["article-1"], "100", undefined);
  expect(value.onSyncSelect).not.toHaveBeenCalled();
});
