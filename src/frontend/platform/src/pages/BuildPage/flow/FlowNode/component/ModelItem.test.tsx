import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ModelItem from "./ModelItem";
const mocks = vi.hoisted(() => ({ models: vi.fn(), retry: vi.fn() }));
vi.mock("@/pages/ModelPage/manage", () => ({ useModel: mocks.models }));
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }));
vi.mock("@/controllers/API/finetune", () => ({ getLlmDefaultModel: vi.fn() }));
const options = [{ value: 337, label: "Root shared", children: [{ value: "933", label: "Default model" }, { value: "936", label: "Selected model" }] }];
beforeEach(() => { mocks.models.mockReturnValue({ llmOptions: options, error: null, refetch: mocks.retry }); });
afterEach(() => { cleanup(); vi.clearAllMocks(); });
it("uses configured assistant candidates and preserves the current selection", () => {
  const change = vi.fn();
  render(<ModelItem agent data={{ value: 936, required: true }} onChange={change} onValidate={vi.fn()} i18nPrefix="model." />);
  expect(mocks.models).toHaveBeenCalledWith("assistant");
  expect(screen.getByText("Selected model")).toBeVisible();
  expect(change).not.toHaveBeenCalled();
});
it("uses the configured first model only when the selection is empty", () => {
  const change = vi.fn();
  render(<ModelItem agent data={{ value: null }} onChange={change} onValidate={vi.fn()} i18nPrefix="model." />);
  expect(change).toHaveBeenCalledWith(933);
});
it("reports errors with retry while preserving a previously selected unavailable model", () => {
  mocks.models.mockReturnValue({ llmOptions: [], error: new Error("config unavailable"), refetch: mocks.retry });
  const change = vi.fn();
  render(<ModelItem agent data={{ value: 936 }} onChange={change} onValidate={vi.fn()} i18nPrefix="model." />);
  expect(screen.getByRole("alert")).toHaveTextContent("modelLoadFailed");
  expect(screen.getByRole("combobox")).toHaveAttribute("aria-disabled", "true");
  fireEvent.click(screen.getByText("retryModelLoad"));
  expect(mocks.retry).toHaveBeenCalled(); expect(change).not.toHaveBeenCalled();
});
