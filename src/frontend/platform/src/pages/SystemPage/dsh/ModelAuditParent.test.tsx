import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ parent: vi.fn() }));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getAuditParent: api.parent,
}));
import { ModelAuditParent } from "./ModelAuditParent";

const row = {
  request_id: "child-request",
  conversation_id: "child",
  session_origin: "subagent" as const,
  parent_conversation_id: "parent",
};
beforeEach(() => vi.clearAllMocks());

it("only locates a parent on explicit click and navigates using server-scoped identity", async () => {
  api.parent.mockResolvedValue({
    status: "AVAILABLE",
    user_id: 20,
    conversation_id: "parent",
  });
  const navigate = vi.fn();
  render(<ModelAuditParent row={row} tenantId={2} onNavigate={navigate} />);
  expect(api.parent).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.sources.parent" }),
  );
  await waitFor(() => expect(navigate).toHaveBeenCalledWith(20, "parent"));
  expect(api.parent).toHaveBeenCalledWith(
    "child-request",
    2,
    expect.any(AbortSignal),
  );
});

it("does not infer a parent for regular forks or fabricate missing parent records", async () => {
  const navigate = vi.fn();
  const view = render(
    <ModelAuditParent
      row={{ ...row, session_origin: "main" }}
      onNavigate={navigate}
    />,
  );
  expect(screen.queryByRole("button")).toBeNull();
  view.rerender(<ModelAuditParent row={row} onNavigate={navigate} />);
  api.parent.mockResolvedValue({ status: "UNAVAILABLE" });
  fireEvent.click(screen.getByRole("button"));
  expect(
    await screen.findByText("dsh.modelAuditView.sources.parent_unavailable"),
  ).toBeVisible();
  expect(navigate).not.toHaveBeenCalled();
});

it("aborts stale navigation when the request is removed", async () => {
  let signal: AbortSignal | undefined;
  api.parent.mockImplementation(
    (_id: string, _tenant: number, current: AbortSignal) => {
      signal = current;
      return new Promise(() => {});
    },
  );
  const view = render(
    <ModelAuditParent row={row} tenantId={2} onNavigate={vi.fn()} />,
  );
  fireEvent.click(screen.getByRole("button"));
  view.unmount();
  expect(signal?.aborted).toBe(true);
});
