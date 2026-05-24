import ApprovalPage from "@/pages/ApprovalPage";
import { render, screen, waitFor } from "@/test/test-utils";
import { within } from "@testing-library/react";
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
const getManagedKnowledgeSpacesApi = vi.fn();
const getDepartmentKnowledgeSpacesApi = vi.fn();
const getRolesApi = vi.fn();
const getUsersApi = vi.fn();

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: (...args: any[]) => toastMock(...args),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, string>) => {
      const map: Record<string, string> = {
        "approvalPage.title": "审批管理",
        "approvalPage.tabFlow": "审批配置",
        "approvalPage.tabException": "异常流程列表",
        "approvalPage.add": "新增",
        "approvalPage.addScenarioTitle": "新增审批场景",
        "approvalPage.confirmAdd": "确认添加",
        "approvalPage.conditionLabel": "可用条件字段",
        "approvalPage.approverSourceLabel": "可用审批人来源",
        "approvalPage.enabled": "启用",
        "approvalPage.routeTitle": "条件分支",
        "approvalPage.createRoute": "新增分支",
        "approvalPage.addRoute": "新增条件分支",
        "approvalPage.editRoute": "编辑条件分支",
        "approvalPage.routeNameLabel": "分支名称",
        "approvalPage.matchConditionHint": "匹配条件",
        "approvalPage.noCondition": "无条件",
        "approvalPage.pleaseSelect": "请选择",
        "approvalPage.routeTypeLabel": "分支结果",
        "approvalPage.routeTypePassFull": "直接通过",
        "approvalPage.routeTypeFlowFull": "进入审批流程",
        "approvalPage.save": "保存",
        "approvalPage.cancel": "取消",
        "approvalPage.edit": "编辑",
        "approvalPage.delete": "删除",
        "approvalPage.flowTitle": "审批流程",
        "approvalPage.createFlow": "新建审批流程",
        "approvalPage.createFlowBtn": "新建流程",
        "approvalPage.addNode": "新增审批节点",
        "approvalPage.addNodeBtn": "新增节点",
        "approvalPage.nodeNameLabel": "节点名称",
        "approvalPage.approverSourceSectionLabel": "审批人来源",
        "approvalPage.addApprover": "添加审批人",
        "approvalPage.nodeModeLabel": "审批方式",
        "approvalPage.nodeModeOr": "或签",
        "approvalPage.nodeModeAnd": "会签",
        "approvalPage.nodeModeOrFull": "任一审批人通过",
        "approvalPage.nodeModeAndFull": "全部审批人通过",
        "approvalPage.exceptionTypeEmpty": "审批人为空",
        "approvalPage.retryAction": "重试",
        "approvalPage.assignApproversAction": "指定审批人",
        "approvalPage.skipNodeAction": "跳过节点",
        "approvalPage.cancelExceptionAction": "取消异常",
        "approvalPage.inputApproverIds": "输入用户 ID，多个用逗号分隔",
        "approvalPage.condition.space_level": "知识空间等级",
        "approvalPage.condition.space_visibility": "空间可见性",
        "approvalPage.condition.source_space_level": "来源知识空间等级",
        "approvalPage.condition.target_space_level": "目标知识空间等级",
        "approvalPage.condition.target_space_id": "目标知识空间",
        "approvalPage.spaceLevel.public": "公共",
        "approvalPage.spaceLevel.department": "部门",
        "approvalPage.spaceLevel.team": "团队",
        "approvalPage.spaceLevel.personal": "个人",
        "approvalPage.spaceVisibility.released": "发布到广场",
        "approvalPage.spaceVisibility.public": "公开",
        "approvalPage.spaceVisibility.approval": "需审核",
        "approvalPage.spaceVisibility.private": "私有",
        "approvalPage.approverSource.direct_user": "指定用户",
        "approvalPage.approverSource.department_admin": "申请人部门管理员",
        "approvalPage.approverSource.knowledge_space_owner": "知识空间 Owner",
        "approvalPage.approverSource.knowledge_space_manager": "知识空间 Manager",
        "approvalPage.approverSource.channel_owner": "频道 Owner",
      };
      return map[key] ?? opts?.defaultValue ?? key;
    },
    i18n: { changeLanguage: vi.fn(), language: "zh-Hans" },
  }),
  Trans: ({ children }: { children: any }) => children,
  initReactI18next: { type: "3rdParty", init: vi.fn() },
}));

vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: (params: any) => params.onOk?.(() => {}),
}));

vi.mock("@/controllers/API/user", () => ({
  getRolesApi: (...a: any[]) => getRolesApi(...a),
  getUsersApi: (...a: any[]) => getUsersApi(...a),
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

vi.mock("@/controllers/API/knowledgeSpace", () => ({
  getManagedKnowledgeSpacesApi: (...a: any[]) => getManagedKnowledgeSpacesApi(...a),
}));

vi.mock("@/controllers/API/departmentKnowledgeSpace", () => ({
  getDepartmentKnowledgeSpacesApi: (...a: any[]) => getDepartmentKnowledgeSpacesApi(...a),
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
  getRolesApi.mockResolvedValue([]);
  getUsersApi.mockResolvedValue({ data: [] });
  getManagedKnowledgeSpacesApi.mockResolvedValue([
    { id: 101, name: "公共空间A", space_kind: "normal" },
  ]);
  getDepartmentKnowledgeSpacesApi.mockResolvedValue([
    { id: 202, name: "部门空间B", space_kind: "department", department_name: "研发部" },
  ]);
});

function getSelectWithOptionValue(value: string): HTMLSelectElement {
  const select = screen
    .getAllByRole("combobox")
    .find((el) => Array.from(el.querySelectorAll("option")).some((option) => option.value === value));

  if (!select) {
    throw new Error(`select with option value "${value}" not found`);
  }

  return select as HTMLSelectElement;
}

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
    await user.selectOptions(getSelectWithOptionValue("pass"), "pass");

    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalRouteApi).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ route_name: "测试分支" }),
      );
    });
    expect(listApprovalRoutesApi).toHaveBeenCalledTimes(2);
  });

  it("shows Shougang space level condition fields from preset and submits selected enum value", async () => {
    const user = userEvent.setup();
    listApprovalScenarioPresetsApi.mockResolvedValue([
      {
        scenario_code: "knowledge_space_file_publish_request",
        scenario_name: "知识空间文件发布审批",
        handler_key: "knowledge_space_file_publish_request",
        condition_fields: ["source_space_level", "target_space_level"],
        approver_source_types: [
          "direct_user",
          "department_admin",
          "knowledge_space_owner",
          "knowledge_space_manager",
        ],
      },
    ]);
    listApprovalScenariosApi.mockResolvedValue([
      {
        id: 31,
        scenario_code: "knowledge_space_file_publish_request",
        scenario_name: "知识空间文件发布审批",
        enabled: true,
      },
    ]);
    listApprovalRoutesApi.mockResolvedValue([]);

    render(<ApprovalPage />);
    await screen.findAllByText("知识空间文件发布审批");

    await user.click(screen.getByRole("button", { name: /新增分支/ }));
    await screen.findByText("新增条件分支");

    const fieldSelect = getSelectWithOptionValue("target_space_level");
    expect(within(fieldSelect).getByRole("option", { name: "来源知识空间等级" })).toHaveValue("source_space_level");
    expect(within(fieldSelect).getByRole("option", { name: "目标知识空间等级" })).toHaveValue("target_space_level");

    await user.selectOptions(fieldSelect, "target_space_level");

    const valueSelect = getSelectWithOptionValue("personal");
    expect(within(valueSelect).getByRole("option", { name: "公共" })).toHaveValue("public");
    expect(within(valueSelect).getByRole("option", { name: "部门" })).toHaveValue("department");
    expect(within(valueSelect).getByRole("option", { name: "团队" })).toHaveValue("team");
    expect(within(valueSelect).getByRole("option", { name: "个人" })).toHaveValue("personal");

    await user.selectOptions(valueSelect, "department");
    await user.type(screen.getByPlaceholderText("如：管理员直接通过"), "部门空间发布");
    await user.selectOptions(getSelectWithOptionValue("pass"), "pass");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalRouteApi).toHaveBeenCalledWith(
        31,
        expect.objectContaining({
          match_config: { field: "target_space_level", value: "department" },
        }),
      );
    });
  });

  it("shows Shougang create space visibility as an enum condition and submits selected value", async () => {
    const user = userEvent.setup();
    listApprovalScenarioPresetsApi.mockResolvedValue([
      {
        scenario_code: "knowledge_space_create_request",
        scenario_name: "知识空间创建审批",
        handler_key: "knowledge_space_create_request",
        condition_fields: ["applicant_role", "space_level", "space_visibility"],
        approver_source_types: ["direct_user", "department_admin"],
      },
    ]);
    listApprovalScenariosApi.mockResolvedValue([
      {
        id: 34,
        scenario_code: "knowledge_space_create_request",
        scenario_name: "知识空间创建审批",
        enabled: true,
      },
    ]);
    listApprovalRoutesApi.mockResolvedValue([]);

    render(<ApprovalPage />);
    await screen.findAllByText("知识空间创建审批");

    await user.click(screen.getByRole("button", { name: /新增分支/ }));
    await screen.findByText("新增条件分支");

    const fieldSelect = getSelectWithOptionValue("space_visibility");
    expect(within(fieldSelect).getByRole("option", { name: "知识空间等级" })).toHaveValue("space_level");
    expect(within(fieldSelect).getByRole("option", { name: "空间可见性" })).toHaveValue("space_visibility");

    await user.selectOptions(fieldSelect, "space_visibility");

    const valueSelect = getSelectWithOptionValue("released");
    expect(within(valueSelect).getByRole("option", { name: "发布到广场" })).toHaveValue("released");
    expect(within(valueSelect).getByRole("option", { name: "公开" })).toHaveValue("public");
    expect(within(valueSelect).getByRole("option", { name: "需审核" })).toHaveValue("approval");
    expect(within(valueSelect).getByRole("option", { name: "私有" })).toHaveValue("private");

    await user.selectOptions(valueSelect, "approval");
    await user.type(screen.getByPlaceholderText("如：管理员直接通过"), "需审核空间创建");
    await user.selectOptions(getSelectWithOptionValue("pass"), "pass");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalRouteApi).toHaveBeenCalledWith(
        34,
        expect.objectContaining({
          match_config: { field: "space_visibility", value: "approval" },
        }),
      );
    });
  });

  it("uses target_space_id as a searchable target space selector and keeps match_config key", async () => {
    const user = userEvent.setup();
    listApprovalScenarioPresetsApi.mockResolvedValue([
      {
        scenario_code: "knowledge_space_file_publish_request",
        scenario_name: "知识空间文件发布审批",
        handler_key: "knowledge_space_file_publish_request",
        condition_fields: ["target_space_id"],
        approver_source_types: ["direct_user"],
      },
    ]);
    listApprovalScenariosApi.mockResolvedValue([
      {
        id: 32,
        scenario_code: "knowledge_space_file_publish_request",
        scenario_name: "知识空间文件发布审批",
        enabled: true,
      },
    ]);
    listApprovalRoutesApi.mockResolvedValue([]);

    render(<ApprovalPage />);
    await screen.findAllByText("知识空间文件发布审批");

    await user.click(screen.getByRole("button", { name: /新增分支/ }));
    await screen.findByText("新增条件分支");

    await user.selectOptions(getSelectWithOptionValue("target_space_id"), "target_space_id");

    await waitFor(() => {
      expect(getManagedKnowledgeSpacesApi).toHaveBeenCalledWith({ order_by: "name" });
      expect(getDepartmentKnowledgeSpacesApi).toHaveBeenCalledWith({ order_by: "name" });
    });

    const targetSpaceSelect = getSelectWithOptionValue("202");
    expect(within(targetSpaceSelect).getByRole("option", { name: "公共空间A" })).toHaveValue("101");
    expect(within(targetSpaceSelect).getByRole("option", { name: "部门空间B（研发部）" })).toHaveValue("202");

    await user.selectOptions(targetSpaceSelect, "202");
    await user.type(screen.getByPlaceholderText("如：管理员直接通过"), "发布到部门空间");
    await user.selectOptions(getSelectWithOptionValue("pass"), "pass");
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalRouteApi).toHaveBeenCalledWith(
        32,
        expect.objectContaining({
          match_config: { field: "target_space_id", value: "202" },
        }),
      );
    });
  });

  it("filters approver source choices by Shougang publish preset", async () => {
    const user = userEvent.setup();
    listApprovalScenarioPresetsApi.mockResolvedValue([
      {
        scenario_code: "knowledge_space_file_publish_request",
        scenario_name: "知识空间文件发布审批",
        handler_key: "knowledge_space_file_publish_request",
        condition_fields: [],
        approver_source_types: [
          "direct_user",
          "department_admin",
          "knowledge_space_owner",
          "knowledge_space_manager",
        ],
      },
    ]);
    listApprovalScenariosApi.mockResolvedValue([
      {
        id: 33,
        scenario_code: "knowledge_space_file_publish_request",
        scenario_name: "知识空间文件发布审批",
        enabled: true,
      },
    ]);

    render(<ApprovalPage />);
    await screen.findByText("审批流程");

    await user.click(screen.getByRole("button", { name: /新增节点/ }));
    await screen.findByText("新增审批节点");

    const sourceSelect = getSelectWithOptionValue("knowledge_space_manager");
    expect(within(sourceSelect).getByRole("option", { name: "指定用户" })).toHaveValue("direct_user");
    expect(within(sourceSelect).getByRole("option", { name: "申请人部门管理员" })).toHaveValue("department_admin");
    expect(within(sourceSelect).getByRole("option", { name: "知识空间 Owner" })).toHaveValue("knowledge_space_owner");
    expect(within(sourceSelect).getByRole("option", { name: "知识空间 Manager" })).toHaveValue("knowledge_space_manager");
    expect(within(sourceSelect).queryByRole("option", { name: "频道 Owner" })).not.toBeInTheDocument();
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
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalFlowApi).toHaveBeenCalledWith(
        1,
        expect.objectContaining({ flow_name: "流程 B" }),
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
    await user.click(screen.getByRole("button", { name: "保存" }));

    await waitFor(() => {
      expect(createApprovalNodeApi).toHaveBeenCalledWith(
        12,
        expect.objectContaining({ node_name: "二级审批" }),
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
