import zh from "../../public/locales/zh-Hans/bs.json";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string, options?: Record<string, unknown>) => {
    const normalized = key.replace(/^bs:/, "");
    const messages = zh as Record<string, unknown>;
    const value = messages[normalized] ?? normalized.split(".").reduce<unknown>((result, segment) =>
      result && typeof result === "object" ? (result as Record<string, unknown>)[segment] : undefined, messages);
    return String(value ?? options?.defaultValue ?? key).replace(/{{(.*?)}}/g, (_, name: string) => String(options?.[name] ?? ""));
  } }),
}));
vi.mock("@/controllers/API/user", () => ({ getRolesApi: vi.fn(async () => []), getUsersApi: vi.fn(async () => ({ data: [], total: 0 })) }));
import { getUsersApi } from "@/controllers/API/user";
import { NodeDialog } from "@/pages/ApprovalPage/NodeDialog";
import ApprovalPage from "@/pages/ApprovalPage";
import { render, screen, waitFor } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── mocks ─────────────────────────────────────────────────────────────────

const toastMock = vi.fn();
const cancelApprovalExceptionApi = vi.fn();
const getApprovalInstanceDetailForAdminApi = vi.fn();
const listApprovalScenarioPresetsApi = vi.fn();
const listApprovalScenariosApi = vi.fn();
const listApprovalExceptionsApi = vi.fn();
const listApprovalRoutesApi = vi.fn();
const listApprovalFlowsApi = vi.fn();
const listApprovalNodesApi = vi.fn();
const createApprovalScenarioApi = vi.fn();
const createApprovalRouteApi = vi.fn();
const createApprovalFlowApi = vi.fn();
const setApprovalFlowNodesApi = vi.fn();
const updateApprovalRouteApi = vi.fn();
const updateApprovalFlowApi = vi.fn();
const retryApprovalExceptionApi = vi.fn();
const updateApprovalScenarioApi = vi.fn();
const deleteApprovalScenarioApi = vi.fn();
const deleteApprovalRouteApi = vi.fn();
const reorderApprovalRoutesApi = vi.fn();
const deleteApprovalFlowApi = vi.fn();

vi.mock('@bisheng/ui', async () => {
const actual = await vi.importActual<typeof import('@bisheng/ui')>('@bisheng/ui');
const previous = await (() => ({
  toast: (...args: any[]) => toastMock(...args),
}))();
const hooks = Reflect.get(previous, 'useToast')?.() ?? {};
return { ...actual, notification: { ...actual.notification, open: Reflect.get(previous, 'toast') ?? Reflect.get(hooks, 'toast') ?? actual.notification.open }, toast: { ...actual.toast, show: Reflect.get(previous, 'message') ?? Reflect.get(hooks, 'message') ?? actual.toast.show } };
});

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: (params: any) => params.onOk?.(() => {}),
}));

vi.mock("@/controllers/API/approval", () => ({
  cancelApprovalExceptionApi: (...a: unknown[]) => cancelApprovalExceptionApi(...a),
  getApprovalInstanceDetailForAdminApi: (...a: unknown[]) => getApprovalInstanceDetailForAdminApi(...a),
  listApprovalScenarioPresetsApi: (...a: any[]) => listApprovalScenarioPresetsApi(...a),
  listApprovalScenariosApi: (...a: any[]) => listApprovalScenariosApi(...a),
  listApprovalExceptionsApi: (...a: any[]) => listApprovalExceptionsApi(...a),
  listApprovalRoutesApi: (...a: any[]) => listApprovalRoutesApi(...a),
  listApprovalFlowsApi: (...a: any[]) => listApprovalFlowsApi(...a),
  listApprovalNodesApi: (...a: any[]) => listApprovalNodesApi(...a),
  createApprovalScenarioApi: (...a: any[]) => createApprovalScenarioApi(...a),
  createApprovalRouteApi: (...a: any[]) => createApprovalRouteApi(...a),
  createApprovalFlowApi: (...a: any[]) => createApprovalFlowApi(...a),
  setApprovalFlowNodesApi: (...a: any[]) => setApprovalFlowNodesApi(...a),
  updateApprovalRouteApi: (...a: any[]) => updateApprovalRouteApi(...a),
  updateApprovalFlowApi: (...a: any[]) => updateApprovalFlowApi(...a),
  retryApprovalExceptionApi: (...a: any[]) => retryApprovalExceptionApi(...a),
  updateApprovalScenarioApi: (...a: any[]) => updateApprovalScenarioApi(...a),
  deleteApprovalScenarioApi: (...a: any[]) => deleteApprovalScenarioApi(...a),
  deleteApprovalRouteApi: (...a: any[]) => deleteApprovalRouteApi(...a),
  reorderApprovalRoutesApi: (...a: any[]) => reorderApprovalRoutesApi(...a),
  deleteApprovalFlowApi: (...a: any[]) => deleteApprovalFlowApi(...a),
}));

function copy(key: string): string {
 const messages = zh as Record<string, unknown>;
 const value = messages[key] ?? key.split(".").reduce<unknown>((result, segment) => result && typeof result === "object" ? (result as Record<string, unknown>)[segment] : undefined, messages);
 if (typeof value !== "string") throw new Error(`Missing test message: ${key}`);
 return value;
}

// ── fixtures ──────────────────────────────────────────────────────────────

const PRESET = {
  scenario_code: "menu_access_request",
  scenario_name: "Menu access request",
  handler_key: "menu_access_request",
  condition_fields: ["menu_key"],
  approver_source_types: ["applicant_department_admin"],
};

const SCENARIO = {
  id: 1,
  scenario_code: "menu_access_request",
  scenario_name: "Menu access request",
  enabled: false,
};

const ROUTE = {
  id: 9,
  route_name: "Admin bypass",
  route_type: "pass",
  enabled: true,
  flow_definition_id: null,
};

const FLOW = {
  id: 12,
  flow_code: "menu_default",
  flow_name: "Menu approval flow A",
  is_active: true,
};

const NODE = {
  id: 15,
  node_code: "n1",
  node_name: "Department administrator approval",
  node_order: 1,
  node_mode: "or",
  approver_config: {
    sources: [{ type: "applicant_department_admin", label: "Department administrator" }],
  },
};

const EXCEPTION = {
  id: 88,
  exception_type: "approver_empty",
  instance_id: 18,
  status: "open",
  create_time: "2026-05-20 10:00:00",
  detail: { node_code: "n1" },
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getUsersApi).mockResolvedValue({ data: [{ user_id: 7, user_name: "Tester" }], total: 1 } as Awaited<ReturnType<typeof getUsersApi>>);
  cancelApprovalExceptionApi.mockResolvedValue({});
  getApprovalInstanceDetailForAdminApi.mockResolvedValue({ tasks: [{ task_id: 1, node_order: 1, node_name: "Historical node", status: "approved", approver_user_name: "Tester" }] });
  listApprovalScenarioPresetsApi.mockResolvedValue([PRESET]);
  listApprovalScenariosApi.mockResolvedValue([SCENARIO]);
  listApprovalExceptionsApi.mockResolvedValue([EXCEPTION]);
  listApprovalRoutesApi.mockResolvedValue([ROUTE]);
  listApprovalFlowsApi.mockResolvedValue([FLOW]);
  listApprovalNodesApi.mockResolvedValue([NODE]);
  createApprovalScenarioApi.mockResolvedValue({ id: 2 });
  createApprovalRouteApi.mockResolvedValue({ id: 10 });
  createApprovalFlowApi.mockResolvedValue({ id: 13, flow_code: "flow_b", flow_name: "Flow B" });
  setApprovalFlowNodesApi.mockResolvedValue({ flow_version_id: 2, version_no: 2, nodes: [NODE] });
  updateApprovalRouteApi.mockResolvedValue({});
  updateApprovalFlowApi.mockResolvedValue({});
  retryApprovalExceptionApi.mockResolvedValue({ status: "resolved" });
  updateApprovalScenarioApi.mockResolvedValue({ id: 1, enabled: true });
  deleteApprovalScenarioApi.mockResolvedValue(undefined);
  deleteApprovalRouteApi.mockResolvedValue(undefined);
  reorderApprovalRoutesApi.mockResolvedValue(undefined);
  deleteApprovalFlowApi.mockResolvedValue(undefined);
});

// ── tests ─────────────────────────────────────────────────────────────────

describe("ApprovalPage", () => {
  it("renders page title and loads scenario/route/node data on mount", async () => {
    render(<ApprovalPage />);

    expect(await screen.findByText(copy("approvalPage.title"))).toBeInTheDocument();

    // scenario card appears in the left panel
    const scenarioMatches = await screen.findAllByText("Menu access request");
    expect(scenarioMatches.length).toBeGreaterThan(0);

    // route and node appear in the right panel
    expect(await screen.findByText("Admin bypass")).toBeInTheDocument();
    expect(await screen.findByText("Menu approval flow A")).toBeInTheDocument();
    expect(await screen.findByText("Department administrator approval")).toBeInTheDocument();

    expect(listApprovalScenarioPresetsApi).toHaveBeenCalledTimes(1);
    expect(listApprovalScenariosApi).toHaveBeenCalledTimes(1);
    expect(listApprovalRoutesApi).toHaveBeenCalledWith(1);
    expect(listApprovalFlowsApi).toHaveBeenCalledWith(1);
    expect(listApprovalNodesApi).toHaveBeenCalledWith(12);
  });

  it("opens add-scenario dialog and creates scenario on confirm", async () => {
    const user = userEvent.setup();
    // use a preset NOT already in scenarios so the dropdown is available
    listApprovalScenariosApi.mockResolvedValue([]);
    listApprovalRoutesApi.mockResolvedValue([]);
    listApprovalFlowsApi.mockResolvedValue([]);

    render(<ApprovalPage />);
    await screen.findByText(copy("approvalPage.title"));

    const addBtn = screen.getByRole("button", { name: /新增/ });
    await user.click(addBtn);

    expect(await screen.findByText(copy("approvalPage.addScenarioTitle"))).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: copy("approvalPage.confirmAdd") });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(createApprovalScenarioApi).toHaveBeenCalledWith({
        scenario_code: "menu_access_request",
        scenario_name: "Menu access request",
        enabled: false,
      });
    });
    expect(listApprovalScenariosApi).toHaveBeenCalledTimes(2);
  });

  it("toggles scenario enabled status via the Switch", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findAllByText("Menu access request");

    // The first switch in DOM order is the scenario enable switch (right-panel header);
    // route row switches come after it.
    const switches = screen.getAllByRole("switch");
    await user.click(switches[0]);

    await waitFor(() => {
      expect(updateApprovalScenarioApi).toHaveBeenCalledWith(1, { enabled: true });
    });
  });

  it("opens route dialog, creates a route and reloads routes", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText(copy("approvalPage.routeTitle"));
    await user.click(screen.getByRole("button", { name: /新增分支/ }));

    expect(await screen.findByText(copy("approvalPage.addRoute"))).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText(copy("subjectSearch.routeExample"));
    await user.type(nameInput, "Test branch");
    await user.selectOptions(screen.getByRole("combobox", { name: /绑定审批流程/ }), "12");

    await user.click(screen.getByRole("button", { name: copy("skillManage.form.save") }));

    await waitFor(() => {
      expect(createApprovalRouteApi).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ route_name: "Test branch", flow_definition_id: 12 }),
      );
    });
    expect(listApprovalRoutesApi).toHaveBeenCalledTimes(2);
  });

  it("opens flow dialog and creates a new flow when no flow is preselected", async () => {
    const user = userEvent.setup();
    listApprovalFlowsApi.mockResolvedValue([]);
    listApprovalNodesApi.mockResolvedValue([]);

    render(<ApprovalPage />);
    await screen.findByText(copy("approvalPage.routeTypeFlow"));

    await user.click(screen.getByRole("button", { name: copy("approvalPage.createFlowBtn") }));

    expect(await screen.findByRole("dialog", { name: copy("approvalPage.createFlow") })).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(copy("subjectSearch.flowExample")), "Flow B");
    await user.click(screen.getByRole("button", { name: copy("skillManage.form.save") }));

    await waitFor(() => {
      expect(createApprovalFlowApi).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ flow_name: "Flow B" }),
      );
    });
  });

  it("enters edit mode, adds a node in draft, and saves via set_flow_nodes", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText("Department administrator approval");

    // enter edit mode
    await user.click(screen.getByRole("button", { name: /编辑节点/ }));

    // edit mode indicator appears
    expect(await screen.findByText(/编辑中/)).toBeInTheDocument();

    // add a new node via the dialog
    await user.click(screen.getByRole("button", { name: /新增节点/ }));
    expect(await screen.findByText(copy("approvalPage.addNode"))).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText(copy("subjectSearch.nodeExample")), "Second approval");
    await user.click(screen.getByRole("button", { name: copy("skillManage.form.save") }));

    // new node appears in draft list (not yet persisted)
    expect(await screen.findByText("Second approval")).toBeInTheDocument();
    expect(setApprovalFlowNodesApi).not.toHaveBeenCalled();

    // save changes: triggers set_flow_nodes creating a new version snapshot
    await user.click(screen.getByRole("button", { name: /保存更改/ }));

    await waitFor(() => {
      expect(setApprovalFlowNodesApi).toHaveBeenCalledWith(
        12,
        expect.arrayContaining([
          expect.objectContaining({ node_name: "Department administrator approval" }),
          expect.objectContaining({ node_name: "Second approval" }),
        ]),
      );
    });

    // edit mode exits on success
    expect(screen.queryByText(/编辑中/)).not.toBeInTheDocument();
    expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ type: "success" }));
  });

  it("edits a route via the edit button and updates route", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText("Admin bypass");

    // route edit button has aria-label="编辑"; scenario card also has title="编辑"
    // so we click the last one (route row) rather than the first (scenario card no-op)
    const editBtns = screen.getAllByRole("button", { name: copy("skillManage.editAction") }).filter(button => !(button as HTMLButtonElement).disabled);
    await user.click(editBtns[editBtns.length - 1]);

    expect(await screen.findByText(copy("approvalPage.editRoute"))).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText(copy("subjectSearch.routeExample"));
    await user.clear(nameInput);
    await user.type(nameInput, "Updated branch name");
    await user.click(screen.getByRole("button", { name: copy("skillManage.form.save") }));

    await waitFor(() => {
      expect(updateApprovalRouteApi).toHaveBeenCalledWith(
        9,
        expect.objectContaining({ route_name: "Updated branch name" }),
      );
    });
  });

  it("switches to exception tab and retries an exception", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText(copy("approvalPage.title"));
    await user.click(screen.getByRole("tab", { name: copy("approvalPage.tabException") }));

    expect(await screen.findByText(copy("approvalPage.exceptionTypeEmpty"))).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: copy("subjectSearch.retry") }));

    await waitFor(() => {
      expect(retryApprovalExceptionApi).toHaveBeenCalledWith(88, {});
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success" }),
    );
  });

  it("deletes a route via the delete button", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText("Admin bypass");

    const deleteBtns = screen.getAllByRole("button", { name: copy("skillManage.deleteAction") }).filter(button => !(button as HTMLButtonElement).disabled);
    await user.click(deleteBtns[deleteBtns.length - 1]);

    await waitFor(() => {
      expect(deleteApprovalRouteApi).toHaveBeenCalledWith(9);
    });
    expect(listApprovalRoutesApi).toHaveBeenCalledTimes(2);
  });

  it("discards local node edits without sending a new version", async () => {
    const user = userEvent.setup(); render(<ApprovalPage />);
    await screen.findByText("Department administrator approval");
    await user.click(screen.getByRole("button", { name: /编辑节点/ }));
    await user.click(screen.getByRole("button", { name: /新增节点/ }));
    await user.type(screen.getByPlaceholderText(copy("subjectSearch.nodeExample")), "Unsaved node");
    await user.click(screen.getByRole("button", { name: copy("skillManage.form.save") }));
    await user.click(screen.getByRole("button", { name: copy("approvalPage.cancelEditBtn") }));
    expect(screen.queryByText("Unsaved node")).not.toBeInTheDocument();
    expect(setApprovalFlowNodesApi).not.toHaveBeenCalled();
  });

  it("keeps node drafts after a failed save", async () => {
    setApprovalFlowNodesApi.mockRejectedValueOnce(new Error("Save failed"));
    const user = userEvent.setup(); render(<ApprovalPage />);
    await screen.findByText("Department administrator approval");
    await user.click(screen.getByRole("button", { name: /编辑节点/ }));
    await user.click(screen.getByRole("button", { name: /保存更改/ }));
    await waitFor(() => expect(toastMock).toHaveBeenCalledWith(expect.objectContaining({ type: "error" })));
    expect(screen.getByText(/编辑中/)).toBeInTheDocument();
    expect(screen.getByText("Department administrator approval")).toBeInTheDocument();
  });

  it("assigns checked users to an exception with the same retry payload", async () => {
    const user = userEvent.setup(); render(<ApprovalPage />);
    await screen.findByText(copy("approvalPage.title"));
    await user.click(screen.getByRole("tab", { name: copy("approvalPage.tabException") }));
    await user.click(screen.getByRole("button", { name: copy("approvalPage.timeline_actionAssignApprovers") }));
    const save = screen.getByRole("button", { name: copy("skillManage.form.save") });
    expect(save).toBeDisabled();
    await user.click(await screen.findByText("Tester"));
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() => expect(retryApprovalExceptionApi).toHaveBeenCalledWith(88, { action: "assign_approvers", approver_user_ids: [7] }));
  });

  it("requires a cancellation reason and trims it before submitting", async () => {
    const user = userEvent.setup(); render(<ApprovalPage />);
    await screen.findByText(copy("approvalPage.title"));
    await user.click(screen.getByRole("tab", { name: copy("approvalPage.tabException") }));
    await user.click(screen.getByRole("button", { name: copy("approvalPage.cancelExceptionAction") }));
    await user.click(screen.getByRole("button", { name: copy("approvalPage.confirmCancelException") }));
    expect(cancelApprovalExceptionApi).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox"), "  No longer needed  ");
    await user.click(screen.getByRole("button", { name: copy("approvalPage.confirmCancelException") }));
    await waitFor(() => expect(cancelApprovalExceptionApi).toHaveBeenCalledWith(88, "No longer needed"));
  });

  it("uses historical tasks when an exception has no flow snapshot", async () => {
    const user = userEvent.setup(); render(<ApprovalPage />);
    await screen.findByText(copy("approvalPage.title"));
    await user.click(screen.getByRole("tab", { name: copy("approvalPage.tabException") }));
    await user.click(screen.getByRole("button", { name: /审批进度/ }));
    expect(await screen.findByText("Historical node")).toBeInTheDocument();
    expect(getApprovalInstanceDetailForAdminApi).toHaveBeenCalledWith(18);
    await user.click(screen.getByRole("button", { name: /审批进度/ }));
    await user.click(screen.getByRole("button", { name: /审批进度/ }));
    expect(getApprovalInstanceDetailForAdminApi).toHaveBeenCalledTimes(1);
  });


  it("edits direct-user approvers and removes their shared tag", async () => {
    const user = userEvent.setup(), onConfirm = vi.fn();
    render(<NodeDialog open initial={{ node_name: "Node", approver_config: { sources: [{ type: "direct_user", user_ids: [7], user_names: ["Tester"] }] } }} onClose={vi.fn()} onConfirm={onConfirm} />);
    await user.click(screen.getByRole("button", { name: copy("skillManage.editAction") }));
    expect(await screen.findByRole("checkbox")).toBeChecked();
    await user.click(screen.getByRole("button", { name: copy("skillManage.form.cancel") }));
    await user.click(screen.getByRole("button", { name: copy("skillManage.deleteAction") }));
    await user.click(screen.getByRole("button", { name: copy("skillManage.form.save") }));
    expect(onConfirm).toHaveBeenCalledWith({ node_name: "Node", node_mode: "or", approver_config: { sources: [] } });
  });
});
