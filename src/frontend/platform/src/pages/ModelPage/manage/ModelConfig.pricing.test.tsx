import { getLLmServerDetail, updateLLmServer } from "@/controllers/API/finetune";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { cleanup, fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ModelConfig from "./ModelConfig";

// The confirmation answers "确认保存" unless a test declines it.
const confirmation = vi.hoisted(() => ({ accept: true }));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: vi.fn((params: { onOk?: (close: () => void) => void; onClose?: () => void }) =>
    confirmation.accept ? params.onOk?.(() => params.onClose?.()) : params.onClose?.()),
}));
vi.mock("@/components/bs-icons/loading", () => ({ LoadingIcon: () => null, LoadIcon: () => null }));
vi.mock("@/controllers/API/finetune", () => ({
  getLLmServerDetail: vi.fn(), updateLLmServer: vi.fn(), addLLmServer: vi.fn(), deleteLLmServer: vi.fn(),
}));
vi.mock("@/controllers/API/modelPricing", () => ({
  matchPriceCatalog: vi.fn(async () => ({ matched: false, via_name: false, catalog_version: "v", entry: null })),
  getCreditSettings: vi.fn(async () => ({ version: 1, currency: "CNY", credit_value: "0.01", usd_cny_rate: "6.72", base_model_id: null })),
}));
vi.mock("@/controllers/request", () => ({ captureAndAlertRequestErrorHoc: (value: unknown) => value }));
vi.mock("@/contexts/userContext", async () => ({
  userContext: (await import("react")).createContext({ user: { role: "admin" } }),
}));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({ appConfig: { multiTenantEnabled: false } }),
}));
vi.mock("@/hooks/useAdminScope", () => ({ useAdminScope: () => ({ scope: {} }) }));
vi.mock("./tabs/WorkbenchModel", () => ({ useLinsightConfig: () => ({ refetch: vi.fn() }) }));
vi.mock("./useLink", () => ({ useModelProviderInfo: () => null }));
vi.mock("./ModelDiscovery", () => ({ ModelDiscovery: () => null }));
vi.mock("./CustomForm", async () => {
  const { forwardRef, useImperativeHandle } = await import("react");
  return {
    CustomForm: forwardRef((_props, ref) => {
      useImperativeHandle(ref, () => ({ getData: () => [{ openai_api_key: "fixture" }, ""] }));
      return null;
    }),
  };
});

const SAVED = { currency: "CNY", input: "2.4", cache_read: "0.48", cache_write: "3", output: "9.6", source: "MANUAL", revision: 2 };
beforeEach(() => {
  confirmation.accept = true;
  vi.mocked(getLLmServerDetail).mockResolvedValue({
    id: 7, name: "provider", type: "qwen", limit_flag: false, limit: 7, config: {},
    models: [{ id: 9, name: "Qwen", model_name: "qwen-max", model_type: "llm", config: { pricing: SAVED } }],
  });
  vi.mocked(updateLLmServer).mockResolvedValue({} as Awaited<ReturnType<typeof updateLLmServer>>);
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const renderConfig = async () => {
  const onAfterSave = vi.fn();
  render(<ModelConfig id={7} onGetName={vi.fn()} onBack={vi.fn()} onReload={vi.fn()}
    onBerforSave={vi.fn(() => false)} onAfterSave={onAfterSave} />);
  await screen.findByDisplayValue("provider");
  return onAfterSave;
};
const editOutputPrice = async (value: string) => {
  fireEvent.click(screen.getByRole("button", { name: "model.configureModel" }));
  const output = await screen.findByLabelText("model.pricing.output");
  fireEvent.change(output, { target: { value } });
};

it("asks before saving a provider whose model price changed, and saves after the confirmation", async () => {
  const onAfterSave = await renderConfig();
  await editOutputPrice("12");
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(onAfterSave).toHaveBeenCalledWith("model.saveSuccess"));
  expect(bsConfirm).toHaveBeenCalledOnce();
  const saved = vi.mocked(updateLLmServer).mock.calls[0][0];
  expect(saved.models[0].config.pricing).toEqual(expect.objectContaining({ output: "12", revision: 2 }));
});

it("does not save when the price confirmation is declined", async () => {
  confirmation.accept = false;
  const onAfterSave = await renderConfig();
  await editOutputPrice("12");
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(bsConfirm).toHaveBeenCalledOnce());
  expect(updateLLmServer).not.toHaveBeenCalled();
  expect(onAfterSave).not.toHaveBeenCalled();
  expect(screen.getByLabelText("model.pricing.output")).toHaveValue("12");
});

it("saves other edits without asking when no price changed", async () => {
  const onAfterSave = await renderConfig();
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(onAfterSave).toHaveBeenCalledWith("model.saveSuccess"));
  expect(bsConfirm).not.toHaveBeenCalled();
});
