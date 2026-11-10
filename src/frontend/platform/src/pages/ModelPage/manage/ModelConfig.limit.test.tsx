import { getLLmServerDetail, updateLLmServer } from "@/controllers/API/finetune";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18next from "i18next";
import { afterEach, expect, it, vi } from "vitest";
import ModelConfig from "./ModelConfig";

const toastShow = vi.hoisted(() => vi.fn());
vi.mock("@bisheng/ui", async () => {
  const actual = await vi.importActual<typeof import("@bisheng/ui")>("@bisheng/ui");
  return { ...actual, toast: { show: toastShow } };
});

vi.mock("@/components/bs-icons/loading", () => ({ LoadingIcon: () => null, LoadIcon: () => null }));
vi.mock("@/controllers/API/finetune", () => ({
  getLLmServerDetail: vi.fn(), updateLLmServer: vi.fn(), addLLmServer: vi.fn(), deleteLLmServer: vi.fn(),
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

afterEach(() => { cleanup(); vi.clearAllMocks(); });

it("keeps the draft and shows the model save copy when the provider save has no specific reason", async () => {
  const model = { id: 9, name: "Qwen", model_name: "qwen-max", model_type: "llm", config: { max_tokens: 256 } };
  vi.mocked(getLLmServerDetail).mockResolvedValue({
    id: 7, name: "provider", type: "qwen", limit_flag: false, limit: 7,
    config: {}, models: [model],
  });
  vi.mocked(updateLLmServer).mockRejectedValue({ message: String(i18next.t("api_errors:fallback")) });
  const onBack = vi.fn();
  const onAfterSave = vi.fn();
  render(<ModelConfig id={7} onGetName={vi.fn()} onBack={onBack} onReload={vi.fn()}
    onBerforSave={vi.fn(() => false)} onAfterSave={onAfterSave} />);
  await screen.findByDisplayValue("provider");
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(toastShow).toHaveBeenCalledWith({
    type: "error", message: "model.saveFailed",
  }));
  expect(onBack).not.toHaveBeenCalled();
  expect(onAfterSave).not.toHaveBeenCalled();
  expect(screen.getByDisplayValue("provider")).toBeInTheDocument();
});

it("shows a specific save failure and reports a successful edit as saved", async () => {
  const model = { id: 9, name: "Qwen", model_name: "qwen-max", model_type: "llm", config: { max_tokens: 256 } };
  vi.mocked(getLLmServerDetail).mockResolvedValue({
    id: 7, name: "provider", type: "qwen", limit_flag: false, limit: 7,
    config: {}, models: [model],
  });
  vi.mocked(updateLLmServer).mockRejectedValueOnce({ message: "服务提供方名称重复，请修改" });
  const onAfterSave = vi.fn();
  render(<ModelConfig id={7} onGetName={vi.fn()} onBack={vi.fn()} onReload={vi.fn()}
    onBerforSave={vi.fn(() => false)} onAfterSave={onAfterSave} />);
  await screen.findByDisplayValue("provider");
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(toastShow).toHaveBeenCalledWith({
    type: "error", message: "服务提供方名称重复，请修改",
  }));
  vi.mocked(updateLLmServer).mockResolvedValueOnce({} as Awaited<ReturnType<typeof updateLLmServer>>);
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(onAfterSave).toHaveBeenCalledWith("model.updateSuccess"));
});

it.each([true, false])("preserves daily quota state %s and saves changes through the original fields", async (enabled) => {
  const model = { id: 9, name: "Qwen", model_name: "qwen-max", model_type: "llm", config: { max_tokens: 256 } };
  vi.mocked(getLLmServerDetail).mockResolvedValue({
    id: 7, name: "provider", type: "qwen", limit_flag: enabled, limit: 7,
    config: {}, models: [model],
  });
  vi.mocked(updateLLmServer).mockResolvedValue({} as Awaited<ReturnType<typeof updateLLmServer>>);
  render(<ModelConfig id={7} onGetName={vi.fn()} onBack={vi.fn()} onReload={vi.fn()}
    onBerforSave={vi.fn(() => false)} onAfterSave={vi.fn()} />);
  await screen.findByDisplayValue("provider");
  const toggle = screen.getByRole("switch");
  expect(toggle.getAttribute("aria-checked")).toBe(String(enabled));
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(updateLLmServer).toHaveBeenCalledWith(expect.objectContaining({
    id: 7, limit_flag: enabled, limit: 7, models: [model],
  })));
  await waitFor(() => expect(screen.getByRole("button", { name: "model.save" })).toBeEnabled());
  vi.mocked(updateLLmServer).mockClear();
  fireEvent.click(toggle);
  fireEvent.change(screen.getByRole("spinbutton"), { target: { value: "9" } });
  fireEvent.click(screen.getByRole("button", { name: "model.save" }));
  await waitFor(() => expect(updateLLmServer).toHaveBeenCalledWith(expect.objectContaining({
    id: 7, limit_flag: !enabled, limit: 9, models: [model],
  })));
});
