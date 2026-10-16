import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
const api = vi.hoisted(() => ({ mode: vi.fn(), save: vi.fn() }));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getAuditMode: api.mode,
  saveAuditMode: api.save,
}));
import { ModelAuditMode } from "./ModelAuditMode";

beforeEach(() => {
  vi.resetAllMocks();
  api.mode.mockResolvedValue({
    mode: "OFF",
    version: 1,
    content_available: false,
  });
  api.save.mockResolvedValue({
    mode: "METADATA",
    version: 2,
    content_available: false,
  });
});

function openModes() {
  if (!screen.queryByRole("combobox"))
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.configure" }),
    );
  fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
}

describe("audit encryption readiness", () => {
  it("explains missing keys, disables content selection and still allows metadata", async () => {
    render(<ModelAuditMode tenantId={2} canConfigure />);
    await screen.findByText("dsh.modelAuditView.contentKeyMissing");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(
      screen.getByRole("button", { name: "dsh.modelAuditView.configure" }),
    ).toHaveAttribute("aria-expanded", "false");
    openModes();
    expect(
      await screen.findByRole("option", {
        name: "dsh.modelAuditView.modes.CONTENT",
      }),
    ).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(
      screen.getByRole("option", { name: "dsh.modelAuditView.modes.METADATA" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "dsh.save" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith(
        2,
        expect.objectContaining({ version: 1 }),
        "METADATA",
      ),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.configure" }),
    );
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(
      screen.getByText("dsh.modelAuditView.contentKeyMissing"),
    ).toBeVisible();
  });

  it("keeps an existing content policy visible with a key-loss alert and allows disabling it", async () => {
    api.mode.mockResolvedValue({
      mode: "CONTENT",
      version: 2,
      content_available: false,
    });
    api.save.mockResolvedValue({
      mode: "OFF",
      version: 3,
      content_available: false,
    });
    render(<ModelAuditMode tenantId={2} canConfigure />);
    await screen.findByText("dsh.modelAuditView.contentKeyLost");
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.configure" }),
    );
    expect(screen.getByRole("combobox")).toHaveTextContent(
      "dsh.modelAuditView.modes.CONTENT",
    );
    openModes();
    fireEvent.click(
      await screen.findByRole("option", {
        name: "dsh.modelAuditView.modes.OFF",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "dsh.save" }));
    await screen.findByText("dsh.modelAuditView.contentKeyMissing");
    expect(api.save).toHaveBeenCalledWith(
      2,
      expect.objectContaining({ version: 2 }),
      "OFF",
    );
  });

  it("allows content only after a fresh positive readiness result", async () => {
    api.mode.mockResolvedValue({
      mode: "OFF",
      version: 1,
      content_available: true,
    });
    api.save.mockResolvedValue({
      mode: "CONTENT",
      version: 2,
      content_available: true,
    });
    render(<ModelAuditMode tenantId={2} canConfigure />);
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.configure" }),
    );
    await screen.findByText("dsh.modelAuditView.contentKeyReady");
    openModes();
    fireEvent.click(
      await screen.findByRole("option", {
        name: "dsh.modelAuditView.modes.CONTENT",
      }),
    );
    fireEvent.click(screen.getByRole("button", { name: "dsh.save" }));
    await waitFor(() =>
      expect(api.save).toHaveBeenCalledWith(
        2,
        expect.objectContaining({ version: 1 }),
        "CONTENT",
      ),
    );
  });

  it("does not assume older responses without readiness fields are ready", async () => {
    api.mode.mockResolvedValue({ mode: "OFF", version: 1 });
    render(<ModelAuditMode tenantId={2} canConfigure />);
    await screen.findByText("dsh.modelAuditView.contentReadinessUnknown");
    openModes();
    expect(
      await screen.findByRole("option", {
        name: "dsh.modelAuditView.modes.CONTENT",
      }),
    ).toHaveAttribute("aria-disabled", "true");
    expect(api.save).not.toHaveBeenCalled();
  });

  it("refreshes availability without silently changing a persisted content policy", async () => {
    api.mode
      .mockResolvedValueOnce({
        mode: "CONTENT",
        version: 2,
        content_available: true,
      })
      .mockResolvedValueOnce({
        mode: "CONTENT",
        version: 2,
        content_available: false,
      });
    render(<ModelAuditMode tenantId={2} canConfigure={false} />);
    await screen.findByText("dsh.modelAuditView.modes.CONTENT");
    fireEvent.click(
      screen.getByRole("button", { name: "dsh.modelAuditView.refresh_mode" }),
    );
    await screen.findByText("dsh.modelAuditView.contentKeyLost");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "dsh.modelAuditView.configure" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "dsh.save" })).toBeNull();
    expect(api.save).not.toHaveBeenCalled();
  });
});
