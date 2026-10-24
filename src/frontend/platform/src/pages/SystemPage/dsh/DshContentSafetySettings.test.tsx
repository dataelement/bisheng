import * as React from "react";
import { act, render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DshContentSafetySettings } from "@/pages/SystemPage/dsh/DshContentSafetySettings";
import { validateDshSensitivePolicy } from "@/pages/SystemPage/dsh/useDshContentSafety";
import type { DshSensitivePolicy, DshSensitivePolicyCommand, DshSafetyCapabilities } from "@/types/dshContentSafety";
const transport = vi.hoisted(() => ({ get: vi.fn(), caps: vi.fn(), save: vi.fn() }));
vi.mock("@/controllers/API/dshContentSafety", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/controllers/API/dshContentSafety")>()),
  getDshSensitivePolicy: (...args: unknown[]) => transport.get(...args),
  getDshSafetyCapabilities: (...args: unknown[]) => transport.caps(...args),
  saveDshSensitivePolicy: (...args: unknown[]) => transport.save(...args),
}));
const limits = {
  custom_words_max_bytes: 1048576,
  effective_words_max_count: 30000,
  effective_words_max_bytes: 1048576,
  word_max_codepoints: 256,
  request_max_bytes: 33554432,
  response_max_bytes: 33554432,
  event_max_bytes: 8388608,
  rule_refs_max_count: 20,
};
const base: DshSensitivePolicy = {
  version: 1,
  enabled: true,
  input_enabled: true,
  output_enabled: false,
  words_types: ["2"],
  custom_words: "Synthetic word",
  auto_reply: "Tenant literal Ω",
  builtin_digest: "a".repeat(64),
  effective_word_count: 1,
  limits,
};
const caps: DshSafetyCapabilities = {
  available: true,
  enabled: true,
  configuration_ready: true,
  builtin_digest: "a".repeat(64),
  limits,
};
const saveButton = () => screen.getByRole("button", { name: "dsh.contentSafety.actions.save" }) as HTMLButtonElement;
const refreshButton = () => screen.getByRole("button", { name: "dsh.contentSafety.actions.refresh" });
const words = () =>
  screen.getByRole("textbox", { name: "dsh.contentSafety.settings.custom_words" }) as HTMLTextAreaElement;
const reply = () =>
  screen.getByRole("textbox", { name: "dsh.contentSafety.settings.auto_reply" }) as HTMLTextAreaElement;
const checkbox = (key: string) =>
  screen.getByRole("checkbox", { name: "dsh.contentSafety.settings." + key }) as HTMLButtonElement;
async function mounted(tenantId = 101, canConfigure = true) {
  const view = render(<DshContentSafetySettings tenantId={tenantId} canConfigure={canConfigure} />);
  await waitFor(() => expect(words().value).toBe("Synthetic word"));
  return view;
}
beforeEach(() => {
  transport.get.mockReset().mockResolvedValue(base);
  transport.caps.mockReset().mockResolvedValue(caps);
  transport.save.mockReset().mockImplementation(async (_tenant: number, command: DshSensitivePolicyCommand) => ({
    ...base,
    ...command,
    version: command.expected_version + 1,
    effective_within_seconds: 5,
  }));
});
afterEach(cleanup);
// Coverage AC: AC-02, AC-07, AC-09, AC-10, AC-56.
describe("content safety settings with the real local v4 lifecycle", () => {
  it("provides its own v4 context and forwards the explicit target tenant", async () => {
    render(<DshContentSafetySettings tenantId={101} canConfigure />);
    await waitFor(() => expect(words().value).toBe("Synthetic word"));
    expect(transport.caps.mock.calls[0][0]).toBe(101);
    expect(transport.caps.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
    expect(screen.getByText("dsh.contentSafety.settings.activation_hint")).toBeTruthy();
  });
  it.each([undefined, 409])("keeps a failed save private while retaining feedback and draft: %s", async (status) => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      await mounted();
      const sensitiveDraft = "Synthetic private policy draft";
      fireEvent.change(words(), { target: { value: sensitiveDraft } });
      const failure = Object.assign(new Error("Synthetic transport failure"), {
        config: { data: JSON.stringify({ custom_words: sensitiveDraft }), headers: { Authorization: "Bearer synthetic-fixture" } },
        ...(status ? { response: { status } } : {}),
      });
      transport.save.mockRejectedValueOnce(failure);
      fireEvent.click(saveButton());
      await screen.findByText(status ? "dsh.contentSafety.errors.version_conflict" : "dsh.contentSafety.errors.save_failed");
      expect(words().value).toBe(sensitiveDraft);
      expect(transport.save).toHaveBeenCalledOnce();
      expect(logged).not.toHaveBeenCalled();
    } finally {
      logged.mockRestore();
    }
  });
  it("keeps checkboxes in a draft until one atomic save", async () => {
    await mounted();
    fireEvent.click(checkbox("output_enabled"));
    expect(transport.save).not.toHaveBeenCalled();
    fireEvent.click(saveButton());
    await waitFor(() => expect(transport.save).toHaveBeenCalledOnce());
    expect(transport.save.mock.calls[0]).toMatchObject([
      101,
      { expected_version: 1, input_enabled: true, output_enabled: true, auto_reply: "Tenant literal Ω" },
    ]);
    await screen.findByText("dsh.contentSafety.actions.saved");
  });
  it("clears the local draft and isolates query keys when the target tenant changes", async () => {
    const view = await mounted();
    fireEvent.change(words(), { target: { value: "Unsaved tenant A" } });
    transport.get.mockResolvedValueOnce({ ...base, custom_words: "Tenant B word", version: 9 });
    view.rerender(<DshContentSafetySettings tenantId={202} canConfigure />);
    await waitFor(() => expect(words().value).toBe("Tenant B word"));
    expect(transport.get.mock.calls.map((args) => args[0])).toEqual([101, 202]);
    expect(screen.queryByDisplayValue("Unsaved tenant A")).toBeNull();
  });
  it("does not let a late old-tenant save overwrite the newly selected tenant", async () => {
    let finish: (value: unknown) => void = () => {};
    transport.save.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = await mounted();
    fireEvent.change(words(), { target: { value: "Unsaved tenant A" } });
    fireEvent.click(saveButton());
    await waitFor(() => expect(transport.save).toHaveBeenCalledOnce());
    transport.get.mockResolvedValueOnce({ ...base, custom_words: "Tenant B word", version: 9 });
    view.rerender(<DshContentSafetySettings tenantId={202} canConfigure />);
    await waitFor(() => expect(words().value).toBe("Tenant B word"));
    await act(async () => finish({ ...base, custom_words: "Saved tenant A", version: 2, effective_within_seconds: 5 }));
    expect(words().value).toBe("Tenant B word");
  });
  it.each([{ response: { status: 409 } }, { response: { status: 200, data: { status_code: 409 } } }])(
    "preserves conflicting edits until explicit refresh before a later CAS: %j",
    async (conflict) => {
      await mounted();
      fireEvent.change(words(), { target: { value: "Conflicting draft" } });
      transport.save.mockRejectedValueOnce(conflict);
      fireEvent.click(saveButton());
      await screen.findByText("dsh.contentSafety.errors.version_conflict");
      expect(words().value).toBe("Conflicting draft");
      expect(saveButton().disabled).toBe(true);
      transport.get.mockResolvedValueOnce({ ...base, version: 7, custom_words: "Server changed elsewhere" });
      fireEvent.click(refreshButton());
      await waitFor(() => expect(saveButton().disabled).toBe(false));
      expect(words().value).toBe("Conflicting draft");
      fireEvent.click(saveButton());
      await waitFor(() => expect(transport.save).toHaveBeenCalledTimes(2));
      expect(transport.save.mock.calls[1][1].expected_version).toBe(7);
    },
  );
  it("keeps a rejected draft and does not automatically retry the mutation", async () => {
    await mounted();
    fireEvent.change(words(), { target: { value: "Retained network draft" } });
    transport.save.mockRejectedValueOnce(new Error("Synthetic offline"));
    fireEvent.click(saveButton());
    await screen.findByText("dsh.contentSafety.errors.save_failed");
    expect(words().value).toBe("Retained network draft");
    expect(transport.save).toHaveBeenCalledOnce();
  });
  it("locks waiting controls and suppresses repeated submissions", async () => {
    let finish: (value: unknown) => void = () => {};
    transport.save.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    await mounted();
    fireEvent.change(words(), { target: { value: "One save only" } });
    const button = saveButton();
    fireEvent.click(button);
    fireEvent.click(button);
    await waitFor(() => expect(transport.save).toHaveBeenCalledOnce());
    expect(checkbox("enabled").disabled).toBe(true);
    expect(words().disabled).toBe(true);
    finish({ ...base, custom_words: "One save only", version: 2, effective_within_seconds: 5 });
    await screen.findByText("dsh.contentSafety.actions.saved");
  });
  it.each([
    ["reply_required", () => fireEvent.change(reply(), { target: { value: "" } })],
    ["words_required", () => fireEvent.change(words(), { target: { value: " ,，|\n " } })],
    ["checks_required", () => fireEvent.click(checkbox("input_enabled"))],
  ])("blocks invalid %s before transport", async (key, change) => {
    await mounted();
    change();
    await screen.findByText("dsh.contentSafety.validation." + key);
    expect(saveButton().disabled).toBe(true);
    expect(transport.save).not.toHaveBeenCalled();
  });
  it("allows an intentional off state with no words or block reply, then re-enabling validates the same draft", async () => {
    await mounted();
    fireEvent.click(checkbox("enabled"));
    fireEvent.change(words(), { target: { value: "" } });
    fireEvent.change(reply(), { target: { value: "" } });
    expect(saveButton().disabled).toBe(false);
    fireEvent.click(saveButton());
    await screen.findByText("dsh.contentSafety.actions.saved");
    expect(transport.save.mock.calls[0][1]).toMatchObject({ enabled: false, custom_words: "", auto_reply: "" });
    fireEvent.click(checkbox("enabled"));
    await screen.findByText("dsh.contentSafety.validation.reply_required");
    expect(saveButton().disabled).toBe(true);
  });
  it("renders permissions as read-only without a second mutable entry", async () => {
    await mounted(101, false);
    expect(checkbox("enabled").disabled).toBe(true);
    expect(words().disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "dsh.contentSafety.actions.save" })).toBeNull();
  });
  it.each([
    [{ ...caps, enabled: false }, "deployment_disabled"],
    [{ ...caps, available: false, configuration_ready: false, builtin_digest: null }, "unavailable"],
  ])("never treats deployment unavailability as a saved off policy", async (state, key) => {
    transport.caps.mockResolvedValueOnce(state);
    render(<DshContentSafetySettings tenantId={101} canConfigure />);
    await screen.findByText("dsh.contentSafety.errors." + key);
    expect(transport.get).not.toHaveBeenCalled();
    expect(screen.queryByText("dsh.contentSafety.settings.default_off")).toBeNull();
  });
  it("recovers a Gateway offline result through an explicit refresh", async () => {
    transport.caps.mockRejectedValueOnce(new Error("Synthetic offline"));
    render(<DshContentSafetySettings tenantId={101} canConfigure />);
    await screen.findByText("dsh.contentSafety.errors.capabilities_unknown");
    fireEvent.click(refreshButton());
    await waitFor(() => expect(words().value).toBe("Synthetic word"));
  });
  it.each([undefined, 0, Number.NaN])("does not request an invalid target tenant: %s", async (tenantId) => {
    render(<DshContentSafetySettings tenantId={tenantId} canConfigure />);
    expect(screen.getByText("dsh.modelAuditView.selectTenant")).toBeTruthy();
    expect(transport.caps).not.toHaveBeenCalled();
    expect(transport.get).not.toHaveBeenCalled();
  });
  it("shows an actual version-zero default-off policy only after successful capability and policy reads", async () => {
    transport.get.mockResolvedValueOnce({
      ...base,
      version: 0,
      enabled: false,
      custom_words: "",
      auto_reply: "",
      effective_word_count: 0,
    });
    render(<DshContentSafetySettings tenantId={101} canConfigure />);
    await screen.findByText("dsh.contentSafety.settings.default_off");
    expect(saveButton()).toBeDisabled();
    expect(checkbox("enabled")).not.toBeChecked();
  });
  it("does not pretend a failed policy read is an off policy", async () => {
    transport.get.mockRejectedValueOnce({ response: { status: 503 } });
    render(<DshContentSafetySettings tenantId={101} canConfigure />);
    await screen.findByText("dsh.contentSafety.errors.load_failed");
    expect(screen.queryByText("dsh.contentSafety.settings.default_off")).toBeNull();
    expect(transport.save).not.toHaveBeenCalled();
  });
  it("uses UTF8 byte and Unicode codepoint boundaries, including while disabled", () => {
    const command: DshSensitivePolicyCommand = {
      expected_version: 1,
      enabled: false,
      input_enabled: false,
      output_enabled: false,
      words_types: [],
      custom_words: String.fromCodePoint(0x5b57).repeat(349526),
      auto_reply: "",
    };
    expect(validateDshSensitivePolicy(command, limits)).toBe("custom_words_too_large");
    expect(
      validateDshSensitivePolicy({ ...command, custom_words: "", auto_reply: "😀".repeat(2048) }, limits),
    ).toBeNull();
    expect(validateDshSensitivePolicy({ ...command, custom_words: "", auto_reply: "😀".repeat(2049) }, limits)).toBe(
      "reply_too_long",
    );
  });
});
