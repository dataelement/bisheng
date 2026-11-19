import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, waitFor } from "@testing-library/react";
import type { VersionHistoryDialogProps } from "@bisheng/knowledge";
import { getFileVersionsApi } from "~/api/knowledge";
import { inspectBatch } from "~/api/knowledgeBatch";
import { getMyResourcePermissions } from "~/api/permission";
import { VersionHistorySheet } from "./VersionHistorySheet";

const mockDialog = jest.fn<void, [VersionHistoryDialogProps]>();
jest.mock("@bisheng/knowledge", () => ({
  VersionHistoryDialog: (props: VersionHistoryDialogProps) => {
    mockDialog(props);
    return null;
  },
}));
jest.mock("~/api/knowledge", () => ({
  getFileVersionsApi: jest.fn(),
  setPrimaryVersionApi: jest.fn(),
  deleteFileVersionApi: jest.fn(),
}));
jest.mock("~/api/knowledgeBatch", () => ({ inspectBatch: jest.fn() }));
jest.mock("~/api/permission", () => ({ getMyResourcePermissions: jest.fn() }));
jest.mock("~/api/request", () => ({ showApiError: jest.fn() }));
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: jest.fn() }) }));
jest.mock("~/hooks", () => ({
  useAuthContext: () => ({ user: { id: "7", role: "member", tenant_id: 42 } }),
  useLocalize: () => (key: string) => key,
}));

const versions = [
  { version_id: 1, version_no: 1, is_primary: true, knowledge_file_id: 15, original_file_name: "primary.pdf" },
  { version_id: 2, version_no: 2, is_primary: false, knowledge_file_id: 17, original_file_name: "history.pdf" },
];

function currentDialog() {
  return mockDialog.mock.calls[mockDialog.mock.calls.length - 1]?.[0];
}

function mount(onChanged?: () => void) {
  const client = new QueryClient({ logger: { log: () => undefined, warn: () => undefined, error: () => undefined } });
  const content = (open: boolean) => (
    <QueryClientProvider client={client}>
      <VersionHistorySheet open={open} spaceId={8} fileId={15} onOpenChange={jest.fn()} onDownload={jest.fn()} onChanged={onChanged} canManage />
    </QueryClientProvider>
  );
  const view = render(content(true));
  return { client, close: () => view.rerender(content(false)) };
}

beforeEach(() => jest.clearAllMocks());

it("checks version history entries using each physical file's effective permissions", async () => {
  jest.mocked(getFileVersionsApi).mockResolvedValue({
    knowledge_id: 8, document_id: 19, title: "Versions", versions,
  });
  jest.mocked(getMyResourcePermissions).mockResolvedValue({
    mode: "INHERIT", actions: ["delete"], sources: [], roster_complete: true,
  });
  jest.mocked(inspectBatch).mockResolvedValue({
    tenant: "42",
    inspection: {
      can_execute: true,
      check_complete: true,
      valid_items: [{ id: 17, type: "file", name: "history.pdf" }],
      invalid_items: [],
      requires_skip_confirmation: false,
      impact: {},
    },
  });
  mount();
  await waitFor(() => expect(currentDialog()?.canDelete?.(versions[1])).toBe(true));
  await waitFor(() => expect(currentDialog()?.canDownload?.(versions[1])).toBe(true));
  expect(currentDialog()?.canDownload?.(versions[0])).toBe(false);
  expect(getMyResourcePermissions).toHaveBeenCalledTimes(1);
  expect(getMyResourcePermissions).toHaveBeenCalledWith("knowledge_file", "17", { signal: expect.any(AbortSignal) });
  expect(inspectBatch).toHaveBeenCalledWith({
    spaceId: 8, operation: "download", items: [{ id: 15, type: "file" }, { id: 17, type: "file" }],
  }, expect.any(AbortSignal));
});

it("does not render history or request file permissions when history belongs to another space", async () => {
  jest.mocked(getFileVersionsApi).mockResolvedValue({
    knowledge_id: 9, document_id: 19, title: "Other space", versions,
  });
  mount();
  await waitFor(() => expect(currentDialog()?.unavailable).toBeTruthy());
  expect(currentDialog()?.data).toBeUndefined();
  expect(getMyResourcePermissions).not.toHaveBeenCalled();
  expect(inspectBatch).not.toHaveBeenCalled();
});

it("aborts a pending history request when the opening closes", async () => {
  jest.mocked(getFileVersionsApi).mockReturnValue(new Promise(() => undefined));
  const view = mount();
  await waitFor(() => expect(getFileVersionsApi).toHaveBeenCalledWith(15, expect.any(AbortSignal)));
  const signal = jest.mocked(getFileVersionsApi).mock.calls[0][1];
  view.close();
  expect(signal?.aborted).toBe(true);
});

it("keeps reading history after the formerly primary file is deleted", async () => {
  let primaryFileId = 15;
  let formerPrimaryDeleted = false;
  jest.mocked(getFileVersionsApi).mockImplementation(async fileId => {
    if (formerPrimaryDeleted && fileId === 15) throw new Error("Former primary no longer exists");
    return {
      knowledge_id: 8,
      document_id: 19,
      title: "Versions",
      versions: versions.filter(version => !formerPrimaryDeleted || version.knowledge_file_id !== 15)
        .map(version => ({ ...version, is_primary: version.knowledge_file_id === primaryFileId })),
    };
  });
  jest.mocked(getMyResourcePermissions).mockResolvedValue({
    mode: "INHERIT", actions: ["delete"], sources: [], roster_complete: true,
  });
  jest.mocked(inspectBatch).mockResolvedValue({
    tenant: "42",
    inspection: { can_execute: true, check_complete: true, valid_items: [], invalid_items: [], requires_skip_confirmation: false, impact: {} },
  });
  const onChanged = jest.fn(() => { void client.invalidateQueries({ queryKey: ["file-versions"] }); });
  const { client } = mount(onChanged);
  await waitFor(() => expect(currentDialog()?.data?.versions[0].is_primary).toBe(true));

  primaryFileId = 17;
  await act(async () => { await currentDialog()?.onChanged?.(17); });
  await waitFor(() => expect(currentDialog()?.data?.versions[1].is_primary).toBe(true));

  formerPrimaryDeleted = true;
  await act(async () => { await currentDialog()?.onChanged?.(17); });
  await waitFor(() => expect(currentDialog()?.data?.versions).toEqual([{ ...versions[1], is_primary: true }]));
  expect(jest.mocked(getFileVersionsApi).mock.calls.map(([fileId]) => fileId)).toEqual([15, 17, 17]);
  expect(onChanged).toHaveBeenCalledTimes(2);
});
