import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  deleteLLMServer,
  precheckLLMServerDelete,
} from "@/controllers/API/llm";
import { getLLmServerDetail } from "@/controllers/API/finetune";
import ModelConfig from "./ModelConfig";

vi.mock("@/controllers/API/finetune", () => ({
  getLLmServerDetail: vi.fn(),
  updateLLmServer: vi.fn(),
  addLLmServer: vi.fn(),
}));
vi.mock("@/controllers/API/llm", async (original) => ({
  ...(await original<typeof import("@/controllers/API/llm")>()),
  deleteLLMServer: vi.fn(),
  precheckLLMServerDelete: vi.fn(),
}));
vi.mock("@/hooks/useAdminScope", () => ({
  useAdminScope: () => ({ scope: {} }),
}));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({
    user: { role: "admin" },
  }),
}));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({
    appConfig: { multiTenantEnabled: false },
  }),
}));
vi.mock("./tabs/WorkbenchModel", () => ({
  useLinsightConfig: () => ({ refetch: vi.fn() }),
}));
vi.mock("./useLink", () => ({ useModelProviderInfo: () => null }));
vi.mock("./ModelDiscovery", () => ({ ModelDiscovery: () => null }));
vi.mock("./CustomForm", async () => {
  const { forwardRef, useImperativeHandle } = await import("react");
  return {
    CustomForm: forwardRef((_props, ref) => {
      useImperativeHandle(ref, () => ({ getData: () => [{}, ""] }));
      return null;
    }),
  };
});
afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

it("only reports success and leaves the editor after the actual deletion promise fulfills", async () => {
  vi.mocked(getLLmServerDetail).mockResolvedValue({
    id: 7,
    name: "provider",
    type: "openai",
    models: [],
    config: {},
  });
  vi.mocked(precheckLLMServerDelete).mockResolvedValue({
    inspection: {
      server_id: 7,
      targets: [],
      source_counts: [],
      slot_counts: [],
      restricted_counts: [],
      qualified_counts: [],
      source_page: {
        data: [],
        page_size: 50,
        has_more: false,
        next_cursor: null,
      },
      check_complete: true,
      blocked: false,
    },
    confirmation: {
      operation: "model_delete_server",
      confirmation_id: "original-plan",
      plan_digest: "a".repeat(64),
      expires_at: "2099-01-01",
    },
  });
  let acknowledge!: () => void;
  vi.mocked(deleteLLMServer).mockReturnValue(
    new Promise<void>((resolve) => {
      acknowledge = resolve;
    }),
  );
  const onBack = vi.fn(),
    onSaved = vi.fn();
  render(
    <ModelConfig
      id={7}
      onGetName={vi.fn()}
      onBack={onBack}
      onBerforSave={vi.fn()}
      onAfterSave={onSaved}
    />,
  );
  await screen.findByDisplayValue("provider");
  fireEvent.click(screen.getByRole("button", { name: "model.delete" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "model.removalConfirmDelete" }),
  );
  await waitFor(() => expect(deleteLLMServer).toHaveBeenCalledOnce());
  expect(onBack).not.toHaveBeenCalled();
  expect(onSaved).not.toHaveBeenCalled();
  acknowledge();
  await waitFor(() => expect(onBack).toHaveBeenCalledOnce());
  expect(onSaved).toHaveBeenCalledWith("model.deleteSuccess");
});

it("keeps shared readonly details from starting any removal or force workflow", async () => {
  vi.mocked(getLLmServerDetail).mockResolvedValue({
    id: 7,
    name: "shared provider",
    type: "openai",
    models: [],
    config: {},
    is_root_shared_readonly: true,
  });
  render(
    <ModelConfig
      id={7}
      onGetName={vi.fn()}
      onBack={vi.fn()}
      onBerforSave={vi.fn()}
      onAfterSave={vi.fn()}
    />,
  );
  await screen.findByDisplayValue("shared provider");
  expect(screen.getByRole("button", { name: "model.delete" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "model.save" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "model.delete" }));
  expect(precheckLLMServerDelete).not.toHaveBeenCalled();
});
