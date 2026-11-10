import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { toast } from "@bisheng/ui";
import {
  confirmMoveFilesApi,
  precheckMoveFilesApi,
  type KnowledgeFile,
  type MoveReview,
} from "~/api/knowledge";
import { useKnowledgeMove } from "./useKnowledgeMove";

const mockConfirm = jest.fn();
const mockShowToast = jest.fn();
jest.mock("~/Providers", () => ({
  useConfirm: () => mockConfirm,
  useToastContext: () => ({ showToast: mockShowToast }),
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/hooks/AuthContext", () => ({
  useAuthContext: () => ({ user: { id: "7" } }),
}));
jest.mock("@bisheng/ui", () => ({ toast: { success: jest.fn() } }), {
  virtual: true,
});
jest.mock("~/api/knowledge", () => ({
  FileType: { FOLDER: "folder", TXT: "txt" },
  precheckMoveFilesApi: jest.fn(),
  confirmMoveFilesApi: jest.fn(),
}));
jest.mock("~/api/knowledgeProcessing", () => ({
  getProcessingJob: jest.fn(async () => ({
    id: "actual-job",
    state: "running",
    revision: 1,
    total_count: 1,
  })),
  listProcessingItems: jest.fn(async () => ({ data: [], total: 0 })),
  listProcessingJobs: jest.fn(async () => ({ data: [], total: 0 })),
  retryProcessingJob: jest.fn(),
}));
const precheck = jest.mocked(precheckMoveFilesApi);
const execute = jest.mocked(confirmMoveFilesApi);
const review: MoveReview = {
  managementTenant: "101",
  precheck: {
    confirmation_id: "same-plan",
    plan_digest: "a".repeat(64),
    can_execute: true,
    check_complete: true,
    expires_at: "2026-11-09T12:00:00Z",
    requires_skip_confirmation: false,
    valid_items: [{ id: 81, type: "file", name: null }],
    invalid_items: [],
    impact: { logical_count: 2, removed_fields: ["old_field"] },
  },
};
const selected = [{ id: "81", type: "txt" }] as KnowledgeFile[];

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, cacheTime: 0 } },
  });
  const onMoved = jest.fn();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return {
    ...renderHook(() => useKnowledgeMove({ spaceId: "10", onMoved }), {
      wrapper,
    }),
    onMoved,
  };
}

beforeEach(() => {
  sessionStorage.clear();
  Object.defineProperty(global.crypto, "randomUUID", {
    configurable: true,
    value: undefined,
  });
  precheck.mockResolvedValue(review);
  mockConfirm.mockResolvedValue(true);
});

it("cancel after real precheck makes no confirmation or moved success", async () => {
  mockConfirm.mockResolvedValue(false);
  const { result, onMoved } = setup();
  act(() => result.current.openMove(selected));
  await act(async () => {
    await expect(
      result.current.handleMoveConfirm("11", "51", true),
    ).rejects.toThrow("move:cancelled");
  });
  expect(precheck).toHaveBeenCalled();
  expect(execute).not.toHaveBeenCalled();
  expect(onMoved).not.toHaveBeenCalled();
});

it("Accepted opens actual job progress and never reports already moved", async () => {
  execute.mockResolvedValue({
    accepted: true,
    job_id: "actual-job",
    state: "accepted",
    reused: false,
  });
  const { result, onMoved } = setup();
  act(() => result.current.openMove(selected));
  await act(async () => {
    await result.current.handleMoveConfirm("11", "51", true);
  });
  await waitFor(() => expect(result.current.moveProgress.open).toBe(true));
  expect(mockShowToast).toHaveBeenCalledWith({
    message: "com_knowledge.move_submitted",
    status: "success",
  });
  expect(onMoved).not.toHaveBeenCalled();
});

it("same-space unknown commit survives reload with the identical opaque plan/key and retains undo", async () => {
  execute
    .mockRejectedValueOnce(new Error("COMMIT ACK lost"))
    .mockResolvedValueOnce({
      moved: [{ id: 81, type: "file", old_parent_id: 50, cross_space: false }],
      invalid: [],
    })
    .mockResolvedValueOnce({
      moved: [
        { id: 81, type: "file", old_parent_id: null, cross_space: false },
      ],
      invalid: [],
    });
  const first = setup();
  act(() => first.result.current.openMove(selected));
  await act(async () => {
    await expect(
      first.result.current.handleMoveConfirm("10", null, false),
    ).rejects.toThrow();
  });
  await waitFor(() =>
    expect(first.result.current.moveProgress.confirmation).not.toBeNull(),
  );
  expect(first.onMoved).not.toHaveBeenCalled();
  first.unmount();
  const { result, onMoved } = setup();
  await act(async () => {
    await result.current.moveProgress.resumeConfirmation();
  });
  const originalKey = execute.mock.calls[0][2];
  expect(originalKey).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  expect(execute).toHaveBeenNthCalledWith(1, "10", review, originalKey);
  expect(execute).toHaveBeenNthCalledWith(
    2,
    "10",
    {
      managementTenant: "101",
      precheck: {
        confirmation_id: review.precheck.confirmation_id,
        plan_digest: review.precheck.plan_digest,
      },
    },
    originalKey,
  );
  expect(sessionStorage.length).toBe(0);
  expect(onMoved).toHaveBeenCalledTimes(1);
  expect(toast.success).toHaveBeenCalledWith(
    "com_knowledge.move_success",
    expect.objectContaining({
      action: expect.objectContaining({ onClick: expect.any(Function) }),
    }),
  );
  const options = jest.mocked(toast.success).mock.calls[0][1];
  await act(async () => {
    options?.action?.onClick();
  });
  await waitFor(() => expect(execute).toHaveBeenCalledTimes(3));
  expect(precheck).toHaveBeenLastCalledWith(
    "10",
    expect.objectContaining({ target_folder_id: "50" }),
  );
});
