import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditMode, AuditModeSnapshot } from "@/types/dshModelAudit";

const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock("@/controllers/request", () => ({ default: api }));
vi.mock("@/controllers/requestStream", () => ({ requestStream: vi.fn() }));
import { ModelAuditMode } from "./ModelAuditMode";

const browserCrypto = globalThis.crypto;
const endpoint = "/api/v1/dsh/admin/model-audit/settings";

beforeEach(() => {
  vi.resetAllMocks();
  // HTTP intranet origins expose getRandomValues, but not randomUUID.
  vi.stubGlobal("crypto", {
    getRandomValues: browserCrypto.getRandomValues.bind(browserCrypto),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("audit mode saves over HTTP through the real API wrapper", () => {
  it.each([
    ["OFF", "METADATA", false],
    ["METADATA", "OFF", false],
    ["CONTENT", "METADATA", false],
    ["OFF", "CONTENT", true],
  ] as const)(
    "persists %s to %s with content availability %s",
    async (initial, target, contentAvailable) => {
      let persisted: AuditModeSnapshot = {
        mode: initial,
        version: 1,
        content_available: contentAvailable,
      };
      api.get.mockImplementation(async () => ({ ...persisted }));
      api.put.mockImplementation(
        async (
          _url: string,
          command: { mode: AuditMode; expected_version: number },
        ) => {
          expect(command.expected_version).toBe(persisted.version);
          persisted = {
            ...persisted,
            mode: command.mode,
            version: persisted.version + 1,
          };
          return { ...persisted };
        },
      );
      render(<ModelAuditMode tenantId={1} canConfigure />);
      fireEvent.click(
        screen.getByRole("button", { name: "dsh.modelAuditView.configure" }),
      );
      await waitFor(() =>
        expect(screen.getByRole("combobox")).not.toBeDisabled(),
      );
      expect(crypto.randomUUID).toBeUndefined();
      fireEvent.keyDown(screen.getByRole("combobox"), { key: "ArrowDown" });
      if (!contentAvailable) {
        expect(
          await screen.findByRole("option", {
            name: "dsh.modelAuditView.modes.CONTENT",
          }),
        ).toHaveAttribute("aria-disabled", "true");
      }
      fireEvent.click(
        await screen.findByRole("option", {
          name: "dsh.modelAuditView.modes." + target,
        }),
      );
      const save = screen.getByRole("button", { name: "dsh.save" });
      expect(save).not.toBeDisabled();
      fireEvent.click(save);
      await waitFor(() =>
        expect(api.put).toHaveBeenCalledWith(endpoint + "/1", {
          operation_id: expect.stringMatching(
            /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
          ),
          expected_version: 1,
          mode: target,
        }),
      );
      await waitFor(() => expect(save).toBeDisabled());
      fireEvent.click(
        screen.getByRole("button", { name: "dsh.modelAuditView.refresh_mode" }),
      );
      await waitFor(() => expect(api.get).toHaveBeenCalledTimes(2));
      await waitFor(() => {
        expect(screen.getByRole("combobox")).not.toBeDisabled();
        expect(screen.getByRole("combobox")).toHaveTextContent(
          "dsh.modelAuditView.modes." + target,
        );
      });
      expect(persisted.mode).toBe(target);
      expect(api.put).toHaveBeenCalledTimes(1);
      expect(
        screen.queryByText("dsh.modelAuditView.loadError"),
      ).not.toBeInTheDocument();
    },
  );
});
