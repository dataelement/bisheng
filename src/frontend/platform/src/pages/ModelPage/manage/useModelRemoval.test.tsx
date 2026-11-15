import { ApiError } from "@bisheng/api-client";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  deleteLLMServer,
  listLLMRemovalSources,
  precheckLLMServerDelete,
  precheckLLMServerUpdate,
  updateLLMServer,
} from "@/controllers/API/llm";
import type {
  LLMServerDraftRequest,
  ModelRemovalPrecheck,
} from "@/controllers/API/llm";
import { useModelRemoval } from "./useModelRemoval";
import { acceptManagementScope } from "@/controllers/managementScope";

const confirm = vi.hoisted(() => vi.fn());
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: confirm,
}));
vi.mock("@/controllers/API/llm", async (original) => ({
  ...(await original<typeof import("@/controllers/API/llm")>()),
  deleteLLMServer: vi.fn(),
  listLLMRemovalSources: vi.fn(),
  precheckLLMServerDelete: vi.fn(),
  precheckLLMServerUpdate: vi.fn(),
  updateLLMServer: vi.fn(),
}));

function preview(
  blocked = false,
  operation:
    "model_update_server" | "model_delete_server" = "model_update_server",
): ModelRemovalPrecheck {
  return {
    inspection: {
      server_id: 7,
      targets: [{ target_type: "model", target_id: "9" }],
      blocked,
      check_complete: true,
      source_counts: [["assistant", blocked ? 1 : 0]],
      slot_counts: [["assistant", blocked ? 2 : 0]],
      restricted_counts: [["assistant", blocked ? 1 : 0]],
      qualified_counts: [["assistant", 0]],
      source_page: {
        data: [],
        page_size: 50,
        has_more: false,
        next_cursor: null,
      },
    },
    confirmation: {
      confirmation_id: "native-confirmation",
      operation,
      plan_digest: "a".repeat(64),
      expires_at: "2099-01-01T00:00:00",
    },
  };
}
function draft(): LLMServerDraftRequest {
  return {
    id: 7,
    name: "provider",
    type: "openai",
    config: { api_key: "original" },
    models: [
      { id: "temporary", name: "new", model_name: "new", model_type: "llm" },
    ],
  };
}
const businessError = (code: number) =>
  new ApiError({ status_code: code }, { message: `error-${code}` });
beforeEach(() => {
  vi.mocked(precheckLLMServerUpdate).mockResolvedValue(preview());
  vi.mocked(precheckLLMServerDelete).mockResolvedValue(
    preview(false, "model_delete_server"),
  );
  vi.mocked(updateLLMServer).mockResolvedValue(
    {} as Awaited<ReturnType<typeof updateLLMServer>>,
  );
  vi.mocked(deleteLLMServer).mockResolvedValue(undefined);
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
  acceptManagementScope(null);
});

describe("the original command and confirmation stay together", () => {
  it("cannot apply an old force acknowledgement to a refreshed impact", async () => {
    vi.mocked(precheckLLMServerUpdate).mockResolvedValue(preview(true));
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.requestUpdate(draft());
    });
    await waitFor(() => expect(result.current.view?.result).toBeDefined());
    act(() => result.current.requestForce());
    const oldConfirmation = confirm.mock.calls[0][0];
    act(() => result.current.refresh());
    await waitFor(() =>
      expect(precheckLLMServerUpdate).toHaveBeenCalledTimes(2),
    );
    await waitFor(() => expect(result.current.view?.pending).toBe(false));
    expect(oldConfirmation.signal.aborted).toBe(true);
    await oldConfirmation.onOk(vi.fn());
    expect(updateLLMServer).not.toHaveBeenCalled();
    act(() => result.current.cancel());
    expect(await outcome).toBe(false);
  });
  it("discards confirmation when the actual management pin changes before submission", async () => {
    acceptManagementScope(101);
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.requestDelete(7);
    });
    await waitFor(() => expect(result.current.view?.result).toBeDefined());
    acceptManagementScope(202);
    act(() => result.current.confirm());
    expect(await outcome).toBe(false);
    expect(result.current.view).toBeNull();
    expect(deleteLLMServer).not.toHaveBeenCalled();
  });

  it("opens a real precheck if a concurrent reference blocks the old ordinary PUT", async () => {
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    const original = vi.fn().mockRejectedValue(businessError(10995));
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.saveUpdate(draft(), original);
    });
    await waitFor(() => expect(result.current.view?.result).toBeDefined());
    expect(original).toHaveBeenCalledOnce();
    expect(precheckLLMServerUpdate).toHaveBeenCalledOnce();
    expect(updateLLMServer).not.toHaveBeenCalled();
    act(() => result.current.cancel());
    expect(await outcome).toBe(false);
  });
  it("keeps non-removal updates on the original path without precheck", async () => {
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    const original = vi.fn().mockResolvedValue({});
    const body = {
      ...draft(),
      models: [{ id: 9, name: "same", model_name: "same", model_type: "llm" }],
    };
    result.current.rememberBaseline([{ id: 9 }]);
    expect(await result.current.saveUpdate(body, original)).toBe(true);
    expect(original).toHaveBeenCalledOnce();
    expect(precheckLLMServerUpdate).not.toHaveBeenCalled();
  });

  it("checks even an empty provider, and cancel never deletes it", async () => {
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.requestDelete(7);
    });
    await waitFor(() => expect(result.current.view?.pending).toBe(false));
    act(() => result.current.cancel());
    expect(await outcome).toBe(false);
    expect(precheckLLMServerDelete).toHaveBeenCalledWith(7);
    expect(deleteLLMServer).not.toHaveBeenCalled();
  });

  it("blocks ordinary removal, then requires a separate explicit force confirmation", async () => {
    vi.mocked(precheckLLMServerUpdate).mockResolvedValue(preview(true));
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    const body = draft();
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.requestUpdate(body);
    });
    body.config!.api_key = "changed after precheck";
    await waitFor(() => expect(result.current.view?.result).toBeDefined());
    act(() => result.current.confirm());
    expect(updateLLMServer).not.toHaveBeenCalled();
    act(() => result.current.requestForce());
    expect(confirm).toHaveBeenCalledOnce();
    await act(async () => {
      await confirm.mock.calls[0][0].onOk(vi.fn());
    });
    expect(await outcome).toBe(true);
    expect(updateLLMServer).toHaveBeenCalledWith(
      expect.objectContaining({
        config: { api_key: "original" },
        models: [expect.not.objectContaining({ id: expect.anything() })],
      }),
      {
        force: true,
        confirmation_id: "native-confirmation",
        plan_digest: "a".repeat(64),
      },
    );
  });

  it("retries an unknown acknowledgement with the exact original DTO and plan", async () => {
    vi.mocked(updateLLMServer).mockRejectedValueOnce(
      new ApiError({ code: "ERR_NETWORK" }, { message: "offline" }),
    );
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.requestUpdate(draft());
    });
    await waitFor(() => expect(result.current.view?.result).toBeDefined());
    act(() => result.current.confirm());
    await waitFor(() => expect(result.current.view?.error).toBe("offline"));
    expect(result.current.view?.dispatched).toBe(true);
    act(() => result.current.requestForce());
    expect(confirm).not.toHaveBeenCalled();
    act(() => result.current.confirm());
    await waitFor(() => expect(result.current.view).toBeNull());
    expect(await outcome).toBe(true);
    expect(updateLLMServer).toHaveBeenCalledTimes(2);
    expect(vi.mocked(updateLLMServer).mock.calls[0]).toEqual(
      vi.mocked(updateLLMServer).mock.calls[1],
    );
    expect(precheckLLMServerUpdate).toHaveBeenCalledOnce();
  });

  it.each([18087, 18088])(
    "requires a new explicit review after impact/expiry error %s",
    async (code) => {
      vi.mocked(updateLLMServer).mockRejectedValueOnce(businessError(code));
      const { result } = renderHook(() =>
        useModelRemoval({ enabled: true, identityKey: "operator" }),
      );
      let outcome!: Promise<boolean>;
      act(() => {
        outcome = result.current.requestUpdate(draft());
      });
      await waitFor(() => expect(result.current.view?.result).toBeDefined());
      act(() => result.current.confirm());
      await waitFor(() => expect(result.current.view?.needsRefresh).toBe(true));
      expect(result.current.view?.result).toBeUndefined();
      act(() => result.current.confirm());
      expect(updateLLMServer).toHaveBeenCalledOnce();
      act(() => result.current.refresh());
      await waitFor(() =>
        expect(result.current.view?.needsRefresh).toBe(false),
      );
      expect(updateLLMServer).toHaveBeenCalledOnce();
      act(() => result.current.cancel());
      expect(await outcome).toBe(false);
    },
  );

  it("never offers force when Coverage failed", async () => {
    vi.mocked(precheckLLMServerDelete).mockRejectedValueOnce(
      businessError(10994),
    );
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.requestDelete(7);
    });
    await waitFor(() => expect(result.current.view?.errorCode).toBe(10994));
    act(() => result.current.requestForce());
    expect(confirm).not.toHaveBeenCalled();
    act(() => result.current.cancel());
    expect(await outcome).toBe(false);
  });

  it("invalidates an open force confirmation when current permission changes", async () => {
    vi.mocked(precheckLLMServerUpdate).mockResolvedValue(preview(true));
    const { result, rerender } = renderHook(
      ({ enabled }) => useModelRemoval({ enabled, identityKey: "operator" }),
      { initialProps: { enabled: true } },
    );
    let outcome!: Promise<boolean>;
    act(() => {
      outcome = result.current.requestUpdate(draft());
    });
    await waitFor(() => expect(result.current.view?.result).toBeDefined());
    act(() => result.current.requestForce());
    const second = confirm.mock.calls[0][0];
    rerender({ enabled: false });
    expect(await outcome).toBe(false);
    expect(second.signal.aborted).toBe(true);
    await second.onOk(vi.fn());
    expect(updateLLMServer).not.toHaveBeenCalled();
  });

  it("pages only the exact retained-list query without creating another plan", async () => {
    const initial = preview(true);
    initial.inspection.source_page = {
      data: [],
      page_size: 50,
      has_more: true,
      next_cursor: "cursor",
    };
    vi.mocked(precheckLLMServerUpdate).mockResolvedValue(initial);
    vi.mocked(listLLMRemovalSources).mockResolvedValue({
      data: [],
      page_size: 50,
      has_more: false,
      next_cursor: null,
    });
    const { result } = renderHook(() =>
      useModelRemoval({ enabled: true, identityKey: "operator" }),
    );
    let outcome!: Promise<boolean>;
    const body = draft();
    body.models.push({
      id: 8,
      name: "retained",
      model_name: "retained",
      model_type: "llm",
    });
    act(() => {
      outcome = result.current.requestUpdate(body);
    });
    await waitFor(() => expect(result.current.view?.page?.has_more).toBe(true));
    act(() => {
      void result.current.loadMore();
    });
    await waitFor(() =>
      expect(result.current.view?.page?.has_more).toBe(false),
    );
    expect(listLLMRemovalSources).toHaveBeenCalledWith({
      server_id: 7,
      retained_model_ids: [8],
      delete_server: false,
      page_size: 50,
      cursor: "cursor",
    });
    expect(precheckLLMServerUpdate).toHaveBeenCalledOnce();
    act(() => result.current.cancel());
    await outcome;
  });
});
