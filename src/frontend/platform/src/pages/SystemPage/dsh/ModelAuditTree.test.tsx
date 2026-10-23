import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import type { AuditTreeNode, AuditTreePage } from "@/types/dshModelAudit";

const api = vi.hoisted(() => ({
  tree: vi.fn(),
  requests: vi.fn(),
  body: vi.fn(),
}));
vi.mock("@/controllers/API/dshModelAudit", () => ({
  getAuditTree: api.tree,
  getAuditGroupRequests: api.requests,
  getModelAudit: vi.fn(),
}));
vi.mock("./ModelAuditBody", () => ({
  ModelAuditBody: (p: unknown) => {
    api.body(p);
    return <p>Body</p>;
  },
}));
import { ModelAuditTree } from "./ModelAuditTree";

const generation = "00000000-0000-0000-0000-000000000001";
function node(id: string, extra: Partial<AuditTreeNode> = {}): AuditTreeNode {
  return {
    conversation_key: id.repeat(64),
    generation,
    conversation_id: "conversation-" + id,
    user_id: 20,
    user_name: "Audit Alice",
    parent_key: "",
    root_key: "a".repeat(64),
    listed_at: "2026-10-19T12:00:00Z",
    last_request_at: "2026-10-19T12:00:00Z",
    updated_at: "2026-10-19T12:00:00Z",
    summary_as_of: "2026-10-19T12:00:00Z",
    request_count: 1,
    abnormal_count: 0,
    relation_state: "MAIN",
    has_children: false,
    match_scope: "SELF",
    own_summary: {
      ready: true,
      request_count: 1,
      abnormal_count: 0,
      known_abnormal: false,
    },
    branch_summary: {
      ready: true,
      request_count: 3,
      abnormal_count: 1,
      known_abnormal: true,
    },
    ...extra,
  };
}
function page(
  items: AuditTreeNode[],
  next_cursor: string | null = null,
): AuditTreePage {
  return {
    items,
    next_cursor,
    scan_limited: false,
    progress: {
      status_ready: true,
      name_ready: true,
      indexing_pending: false,
      hierarchy_ready: true,
    },
  };
}
const query = { tenant_id: 2, limit: 20 };
it("AC-T08/AC-T09: titles render literally, preserve the ID, and fall back without fetching originals", () => {
  const value = node("a", { conversation_title: "<script>e2e-title</script>", title_event_seq: 12 });
  const view = render(tree(value, false));
  const label = screen.getByText("<script>e2e-title</script>");
  expect(label).toHaveAttribute("title", value.conversation_id);
  expect(view.container.querySelector("script")).toBeNull();
  expect(api.body).not.toHaveBeenCalled();
  view.rerender(tree({ ...value, conversation_title: null }, false));
  expect(screen.getByText(value.conversation_id)).toBeVisible();
});
const navigate = vi.fn(),
  refresh = vi.fn();
function tree(value: AuditTreeNode, expanded = true) {
  return (
    <ModelAuditTree
      node={value}
      query={query}
      expanded={expanded}
      onToggle={vi.fn()}
      onNavigate={navigate}
      onRefresh={refresh}
    />
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  api.requests.mockResolvedValue({
    items: [],
    next_cursor: null,
    progress: {},
  });
  api.tree.mockResolvedValue(page([]));
});

it("AC-H01/AC-H06: collapsed tree fetches no requests/children/originals; children stay lazy", async () => {
  const parent = node("a", { has_children: true });
  api.tree.mockResolvedValue(
    page([
      node("b", {
        parent_key: parent.conversation_key,
        relation_state: "LINKED",
      }),
    ]),
  );
  const rendered = render(tree(parent, false));
  expect(api.tree).not.toHaveBeenCalled();
  expect(api.requests).not.toHaveBeenCalled();
  rendered.rerender(tree(parent));
  const child = await screen.findByRole("button", { name: /conversation-b/ });
  expect(
    screen.queryByRole("button", { name: "dsh.modelAuditView.group_all" }),
  ).toBeNull();
  expect(child.getAttribute("aria-expanded")).toBe("false");
  await waitFor(() => expect(api.requests).toHaveBeenCalledTimes(1));
  expect(api.tree.mock.calls[0][2]).toBe(parent.conversation_key);
  expect(api.tree.mock.calls[0][3]).toBe(generation);
  fireEvent.click(child);
  await waitFor(() => expect(api.requests).toHaveBeenCalledTimes(2));
  expect(child.getAttribute("aria-expanded")).toBe("true");
  expect(
    screen.queryByRole("button", { name: "dsh.modelAuditView.group_all" }),
  ).toBeNull();
  expect(api.body).not.toHaveBeenCalled();
});

it("AC-H04/AC-H05: path-only parent does not fetch nonmatching requests and reflects child abnormalities", async () => {
  render(tree(node("a", { match_scope: "DESCENDANT", has_children: true })));
  expect(screen.getByText("dsh.modelAuditView.tree.path_only")).toBeTruthy();
  expect(screen.getByText("dsh.modelAuditView.group_abnormal")).toBeTruthy();
  await screen.findByText("dsh.modelAuditView.tree.no_children");
  expect(api.requests).not.toHaveBeenCalled();
  expect(api.body).not.toHaveBeenCalled();
});

it("AC-H05: incomplete summary is not shown as zero or normal", () => {
  render(
    tree(
      node("a", {
        branch_summary: {
          ready: false,
          request_count: null,
          abnormal_count: null,
          known_abnormal: false,
        },
      }),
      false,
    ),
  );
  expect(
    screen.getByText("dsh.modelAuditView.tree.summary_pending"),
  ).toBeTruthy();
  expect(screen.queryByText("dsh.modelAuditView.summary.NORMAL")).toBeNull();
});

it("AC-H02/AC-H08: child pagination accepts an empty resumable page and stays independent", async () => {
  api.tree
    .mockResolvedValueOnce({ ...page([], "continue-scan"), scan_limited: true })
    .mockResolvedValueOnce(page([node("c")]));
  render(tree(node("a", { has_children: true })));
  await screen.findByText("dsh.modelAuditView.scan_limited");
  expect(screen.queryByText("dsh.modelAuditView.tree.no_children")).toBeNull();
  const next = screen
    .getAllByRole("button", { name: "dsh.next" })
    .find((b) => !b.hasAttribute("disabled"));
  expect(next).toBeTruthy();
  fireEvent.click(next!);
  await screen.findByRole("button", { name: /conversation-c/ });
  expect(api.tree.mock.calls[1][0].cursor).toBe("continue-scan");
  expect(api.requests).toHaveBeenCalledTimes(1);
});

it("AC-H08: failed children can retry; an expired generation requires a root refresh", async () => {
  api.tree
    .mockRejectedValueOnce(new Error("synthetic failure"))
    .mockResolvedValueOnce({
      ...page([]),
      progress: {
        status_ready: true,
        name_ready: true,
        indexing_pending: false,
        refresh_required: true,
      },
    });
  render(tree(node("a", { has_children: true })));
  fireEvent.click(
    await screen.findByRole("button", {
      name: "dsh.modelAuditView.tree.retry",
    }),
  );
  await screen.findByText("dsh.modelAuditView.tree.refresh_required");
  fireEvent.click(
    screen.getByRole("button", { name: "dsh.modelAuditView.tree.retry" }),
  );
  expect(refresh).toHaveBeenCalledTimes(1);
  expect(api.tree).toHaveBeenCalledTimes(2);
});

it("AC-H09: changed filters abort children and ignore the late response", async () => {
  let resolveOld: ((value: AuditTreePage) => void) | undefined;
  api.tree
    .mockImplementationOnce(
      () =>
        new Promise<AuditTreePage>((resolve) => {
          resolveOld = resolve;
        }),
    )
    .mockResolvedValue(page([node("c")]));
  const parent = node("a", { has_children: true });
  const rendered = render(tree(parent));
  await waitFor(() => expect(api.tree).toHaveBeenCalledTimes(1));
  const oldSignal: AbortSignal = api.tree.mock.calls[0][1];
  rendered.rerender(
    <ModelAuditTree
      node={parent}
      query={{ ...query, model_name: "Provider / New" }}
      expanded
      onToggle={vi.fn()}
      onNavigate={navigate}
      onRefresh={refresh}
    />,
  );
  await screen.findByRole("button", { name: /conversation-c/ });
  expect(oldSignal.aborted).toBe(true);
  resolveOld?.(page([node("b")]));
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: /conversation-b/ })).toBeNull(),
  );
});
