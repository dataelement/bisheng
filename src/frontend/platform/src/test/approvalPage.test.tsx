import ApprovalPage from "@/pages/ApprovalPage";
import { render, screen, waitFor } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// ── mocks ─────────────────────────────────────────────────────────────────

const toastMock = vi.fn();
const listApprovalScenarioPresetsApi = vi.fn();
const listApprovalScenariosApi = vi.fn();
const listApprovalExceptionsApi = vi.fn();
const listApprovalRoutesApi = vi.fn();
const listApprovalFlowsApi = vi.fn();
const listApprovalNodesApi = vi.fn();
const createApprovalScenarioApi = vi.fn();
const createApprovalRouteApi = vi.fn();
const createApprovalFlowApi = vi.fn();
const createApprovalNodeApi = vi.fn();
const updateApprovalRouteApi = vi.fn();
const updateApprovalFlowApi = vi.fn();
const updateApprovalNodeApi = vi.fn();
const retryApprovalExceptionApi = vi.fn();
const updateApprovalScenarioApi = vi.fn();
const deleteApprovalScenarioApi = vi.fn();
const deleteApprovalRouteApi = vi.fn();
const reorderApprovalRoutesApi = vi.fn();
const deleteApprovalFlowApi = vi.fn();
const deleteApprovalNodeApi = vi.fn();

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: (...args: any[]) => toastMock(...args),
}));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: (params: any) => params.onOk?.(() => {}),
}));

vi.mock("@/controllers/API/approval", () => ({
  listApprovalScenarioPresetsApi: (...a: any[]) => listApprovalScenarioPresetsApi(...a),
  listApprovalScenariosApi: (...a: any[]) => listApprovalScenariosApi(...a),
  listApprovalExceptionsApi: (...a: any[]) => listApprovalExceptionsApi(...a),
  listApprovalRoutesApi: (...a: any[]) => listApprovalRoutesApi(...a),
  listApprovalFlowsApi: (...a: any[]) => listApprovalFlowsApi(...a),
  listApprovalNodesApi: (...a: any[]) => listApprovalNodesApi(...a),
  createApprovalScenarioApi: (...a: any[]) => createApprovalScenarioApi(...a),
  createApprovalRouteApi: (...a: any[]) => createApprovalRouteApi(...a),
  createApprovalFlowApi: (...a: any[]) => createApprovalFlowApi(...a),
  createApprovalNodeApi: (...a: any[]) => createApprovalNodeApi(...a),
  updateApprovalRouteApi: (...a: any[]) => updateApprovalRouteApi(...a),
  updateApprovalFlowApi: (...a: any[]) => updateApprovalFlowApi(...a),
  updateApprovalNodeApi: (...a: any[]) => updateApprovalNodeApi(...a),
  retryApprovalExceptionApi: (...a: any[]) => retryApprovalExceptionApi(...a),
  updateApprovalScenarioApi: (...a: any[]) => updateApprovalScenarioApi(...a),
  deleteApprovalScenarioApi: (...a: any[]) => deleteApprovalScenarioApi(...a),
  deleteApprovalRouteApi: (...a: any[]) => deleteApprovalRouteApi(...a),
  reorderApprovalRoutesApi: (...a: any[]) => reorderApprovalRoutesApi(...a),
  deleteApprovalFlowApi: (...a: any[]) => deleteApprovalFlowApi(...a),
  deleteApprovalNodeApi: (...a: any[]) => deleteApprovalNodeApi(...a),
}));

// ── fixtures ──────────────────────────────────────────────────────────────

const PRESET = {
  scenario_code: "menu_access_request",
  scenario_name: "菜单权限申请",
  handler_key: "menu_access_request",
  condition_fields: ["menu_key"],
  approver_source_types: ["applicant_department_admin"],
};

const SCENARIO = {
  id: 1,
  scenario_code: "menu_access_request",
  scenario_name: "菜单权限申请",
  enabled: false,
};

const ROUTE = {
  id: 9,
  route_name: "管理员直接通过",
  route_type: "pass",
  enabled: true,
  flow_definition_id: null,
};

const FLOW = {
  id: 12,
  flow_code: "menu_default",
  flow_name: "菜单权限审批流程 A",
  is_active: true,
};

const NODE = {
  id: 15,
  node_code: "n1",
  node_name: "申请人部门管理员审批",
  node_order: 1,
  node_mode: "or",
  approver_config: {
    sources: [{ type: "applicant_department_admin", label: "申请人部门管理员" }],
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
  listApprovalScenarioPresetsApi.mockResolvedValue([PRESET]);
  listApprovalScenariosApi.mockResolvedValue([SCENARIO]);
  listApprovalExceptionsApi.mockResolvedValue([EXCEPTION]);
  listApprovalRoutesApi.mockResolvedValue([ROUTE]);
  listApprovalFlowsApi.mockResolvedValue([FLOW]);
  listApprovalNodesApi.mockResolvedValue([NODE]);
  createApprovalScenarioApi.mockResolvedValue({ id: 2 });
  createApprovalRouteApi.mockResolvedValue({ id: 10 });
  createApprovalFlowApi.mockResolvedValue({ id: 13, flow_code: "flow_b", flow_name: "流程 B" });
  createApprovalNodeApi.mockResolvedValue({ id: 16 });
  updateApprovalRouteApi.mockResolvedValue({});
  updateApprovalFlowApi.mockResolvedValue({});
  updateApprovalNodeApi.mockResolvedValue({});
  retryApprovalExceptionApi.mockResolvedValue({ status: "resolved" });
  updateApprovalScenarioApi.mockResolvedValue({ id: 1, enabled: true });
  deleteApprovalScenarioApi.mockResolvedValue(undefined);
  deleteApprovalRouteApi.mockResolvedValue(undefined);
  reorderApprovalRoutesApi.mockResolvedValue(undefined);
  deleteApprovalFlowApi.mockResolvedValue(undefined);
  deleteApprovalNodeApi.mockResolvedValue(undefined);
});

// ── tests ─────────────────────────────────────────────────────────────────

describe("ApprovalPage", () => {
  it("renders page title and loads scenario/route/node data on mount", async () => {
    render(<ApprovalPage />);

    expect(await screen.findByText("审批管理")).toBeInTheDocument();

    // scenario card appears in the left panel
    const scenarioMatches = await screen.findAllByText("菜单权限申请");
    expect(scenarioMatches.length).toBeGreaterThan(0);

    // route and node appear in the right panel
    expect(await screen.findByText("管理员直接通过")).toBeInTheDocument();
    expect(await screen.findByText("菜单权限审批流程 A")).toBeInTheDocument();
    expect(await screen.findByText("申请人部门管理员审批")).toBeInTheDocument();

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
    await screen.findByText("审批管理");

    const addBtn = screen.getByRole("button", { name: /新增/ });
    await user.click(addBtn);

    expect(await screen.findByText("新增审批场景")).toBeInTheDocument();

    const confirmBtn = screen.getByRole("button", { name: "确认添加" });
    await user.click(confirmBtn);

    await waitFor(() => {
      expect(createApprovalScenarioApi).toHaveBeenCalledWith({
        scenario_code: "menu_access_request",
        scenario_name: "菜单权限申请",
        enabled: false,
      });
    });
    expect(listApprovalScenariosApi).toHaveBeenCalledTimes(2);
  });

  it("toggles scenario enabled status via the Switch", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findAllByText("菜单权限申请");

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

    await screen.findByText("条件分支");
    await user.click(screen.getByRole("button", { name: /新增分支/ }));

    expect(await screen.findByText("新增条件分支")).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText("如：管理员直接通过");
    await user.type(nameInput, "测试分支");

    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalRouteApi).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ route_name: "测试分支" }),
      );
    });
    expect(listApprovalRoutesApi).toHaveBeenCalledTimes(2);
  });

  it("opens flow dialog and creates a new flow when no flow is preselected", async () => {
    const user = userEvent.setup();
    // no existing flows so the button says "新建流程"
    listApprovalFlowsApi.mockResolvedValue([]);
    listApprovalNodesApi.mockResolvedValue([]);

    render(<ApprovalPage />);
    await screen.findByText("审批流程");

    await user.click(screen.getByRole("button", { name: "新建流程" }));

    expect(await screen.findByText("新建审批流程")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("如：菜单权限审批流程 A"), "流程 B");
    await user.type(screen.getByPlaceholderText("如：menu_flow_a"), "flow_b");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalFlowApi).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ flow_name: "流程 B", flow_code: "flow_b" }),
      );
    });
  });

  it("opens node dialog and creates a node", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText("审批流程");
    await user.click(screen.getByRole("button", { name: /新增节点/ }));

    expect(await screen.findByText("新增审批节点")).toBeInTheDocument();

    await user.type(screen.getByPlaceholderText("如：申请人部门管理员审批"), "二级审批");
    await user.type(screen.getByPlaceholderText("如：dept_admin_review"), "level2");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalNodeApi).toHaveBeenCalledWith(
        12,
        expect.objectContaining({ node_name: "二级审批", node_code: "level2" }),
      );
    });
    expect(listApprovalNodesApi).toHaveBeenCalledTimes(2);
  });

  it("edits a route via the edit button and updates route", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText("管理员直接通过");

    // route edit button has aria-label="编辑"; scenario card also has title="编辑"
    // so we click the last one (route row) rather than the first (scenario card no-op)
    const editBtns = screen.getAllByRole("button", { name: "编辑" });
    await user.click(editBtns[editBtns.length - 1]);

    expect(await screen.findByText("编辑条件分支")).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText("如：管理员直接通过");
    await user.clear(nameInput);
    await user.type(nameInput, "修改后分支名");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(updateApprovalRouteApi).toHaveBeenCalledWith(
        9,
        expect.objectContaining({ route_name: "修改后分支名" }),
      );
    });
  });

  it("switches to exception tab and retries an exception", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText("审批管理");
    await user.click(screen.getByRole("button", { name: "异常流程列表" }));

    expect(await screen.findByText("审批人为空")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "重试" }));

    await waitFor(() => {
      expect(retryApprovalExceptionApi).toHaveBeenCalledWith(88, {});
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({ variant: "success" }),
    );
  });

  it("switches to exception tab and assigns approvers for approver_empty", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await user.click(await screen.findByRole("button", { name: "异常流程列表" }));
    await screen.findByText("审批人为空");

    const input = screen.getByPlaceholderText("输入用户 ID，多个用逗号分隔");
    await user.type(input, "101, 202");
    await user.click(screen.getByRole("button", { name: "指定审批人" }));

    await waitFor(() => {
      expect(retryApprovalExceptionApi).toHaveBeenCalledWith(88, {
        action: "assign_approvers",
        approver_user_ids: [101, 202],
      });
    });
  });

  it("skips current node for approver_empty exception", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await user.click(await screen.findByRole("button", { name: "异常流程列表" }));
    await screen.findByText("审批人为空");

    await user.click(screen.getByRole("button", { name: "跳过节点" }));

    await waitFor(() => {
      expect(retryApprovalExceptionApi).toHaveBeenCalledWith(88, {
        action: "skip_node",
      });
    });
  });

  it("deletes a route via the delete button", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    await screen.findByText("管理员直接通过");

    // route delete button has aria-label="删除"
    const deleteBtns = screen.getAllByRole("button", { name: "删除" });
    // first delete btn might be for scenario card (in scenario list hover area)
    // route row delete is in the route row; click the one visible in the route row area
    await user.click(deleteBtns[deleteBtns.length - 1]);

    await waitFor(() => {
      expect(deleteApprovalRouteApi).toHaveBeenCalledWith(9);
    });
    expect(listApprovalRoutesApi).toHaveBeenCalledTimes(2);
  });
});
