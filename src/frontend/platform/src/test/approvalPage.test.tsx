import ApprovalPage from "@/pages/ApprovalPage";
import { render, screen, waitFor } from "@/test/test-utils";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toastMock = vi.fn();
const listApprovalScenarioPresetsApi = vi.fn();
const listApprovalScenariosApi = vi.fn();
const listApprovalExceptionsApi = vi.fn();
const listApprovalRoutesApi = vi.fn();
const createApprovalScenarioApi = vi.fn();
const createApprovalRouteApi = vi.fn();
const retryApprovalExceptionApi = vi.fn();
const updateApprovalScenarioApi = vi.fn();

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  toast: (...args: any[]) => toastMock(...args),
}));

vi.mock("@/controllers/API/approval", () => ({
  listApprovalScenarioPresetsApi: (...args: any[]) => listApprovalScenarioPresetsApi(...args),
  listApprovalScenariosApi: (...args: any[]) => listApprovalScenariosApi(...args),
  listApprovalExceptionsApi: (...args: any[]) => listApprovalExceptionsApi(...args),
  listApprovalRoutesApi: (...args: any[]) => listApprovalRoutesApi(...args),
  createApprovalScenarioApi: (...args: any[]) => createApprovalScenarioApi(...args),
  createApprovalRouteApi: (...args: any[]) => createApprovalRouteApi(...args),
  retryApprovalExceptionApi: (...args: any[]) => retryApprovalExceptionApi(...args),
  updateApprovalScenarioApi: (...args: any[]) => updateApprovalScenarioApi(...args),
}));

describe("ApprovalPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    listApprovalScenarioPresetsApi.mockResolvedValue([
      {
        scenario_code: "menu_access_request",
        scenario_name: "菜单权限申请",
        handler_key: "menu_access_request",
        condition_fields: ["menu_key"],
        approver_source_types: ["tenant_admin"],
      },
    ]);
    listApprovalScenariosApi.mockResolvedValue([
      {
        id: 1,
        scenario_code: "menu_access_request",
        scenario_name: "菜单权限申请",
        enabled: false,
      },
    ]);
    listApprovalExceptionsApi.mockResolvedValue([
      {
        id: 88,
        exception_type: "route_missing",
        instance_id: 18,
        status: "open",
        create_time: "2026-05-20 10:00:00",
      },
    ]);
    listApprovalRoutesApi.mockResolvedValue([
      {
        id: 9,
        route_name: "默认流程",
        route_type: "flow",
        enabled: true,
      },
    ]);
    createApprovalScenarioApi.mockResolvedValue({ id: 2 });
    createApprovalRouteApi.mockResolvedValue({ id: 10, route_name: "新增分支", route_type: "flow" });
    retryApprovalExceptionApi.mockResolvedValue({ status: "resolved" });
    updateApprovalScenarioApi.mockResolvedValue({ id: 1, enabled: true });
  });

  it("loads presets, scenarios, exceptions and routes on mount", async () => {
    render(<ApprovalPage />);

    expect(await screen.findByText("approvalPage.title")).toBeInTheDocument();
    expect(await screen.findByText("菜单权限申请")).toBeInTheDocument();
    expect(await screen.findByText("route_missing #88")).toBeInTheDocument();
    expect(await screen.findByText("默认流程 #9")).toBeInTheDocument();

    expect(listApprovalScenarioPresetsApi).toHaveBeenCalledTimes(1);
    expect(listApprovalScenariosApi).toHaveBeenCalledTimes(1);
    expect(listApprovalExceptionsApi).toHaveBeenCalledTimes(1);
    expect(listApprovalRoutesApi).toHaveBeenCalledWith(1);
  });

  it("creates a scenario from the selected preset and reloads the page", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    const createButton = await screen.findByRole("button", { name: "approvalPage.createScenario" });
    await user.click(createButton);

    await waitFor(() => {
      expect(createApprovalScenarioApi).toHaveBeenCalledWith({
        scenario_code: "menu_access_request",
        scenario_name: "菜单权限申请",
        enabled: false,
      });
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: "success",
        description: "approvalPage.createSuccess",
      }),
    );
    expect(listApprovalScenarioPresetsApi).toHaveBeenCalledTimes(2);
    expect(listApprovalScenariosApi).toHaveBeenCalledTimes(2);
  });

  it("retries an exception and refreshes the page", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    const retryButton = await screen.findByRole("button", { name: "approvalPage.retryAction" });
    await user.click(retryButton);

    await waitFor(() => {
      expect(retryApprovalExceptionApi).toHaveBeenCalledWith(88);
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: "success",
        description: "approvalPage.retrySuccess",
      }),
    );
    expect(listApprovalExceptionsApi).toHaveBeenCalledTimes(2);
  });

  it("creates a route for the selected scenario and reloads route list", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    const routeNameInput = await screen.findByPlaceholderText("approvalPage.routeNamePlaceholder");
    await user.type(routeNameInput, "新增分支");
    await user.click(screen.getByRole("button", { name: "approvalPage.createRoute" }));

    await waitFor(() => {
      expect(createApprovalRouteApi).toHaveBeenCalledWith(1, {
        route_name: "新增分支",
        route_type: "flow",
        sort_order: 1,
        match_config: {},
      });
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: "success",
        description: "approvalPage.routeCreateSuccess",
      }),
    );
    expect(listApprovalRoutesApi).toHaveBeenCalledTimes(2);
  });

  it("toggles scenario enabled status and reloads the page", async () => {
    const user = userEvent.setup();
    render(<ApprovalPage />);

    const enableButton = await screen.findByRole("button", { name: "approvalPage.enableScenario" });
    await user.click(enableButton);

    await waitFor(() => {
      expect(updateApprovalScenarioApi).toHaveBeenCalledWith(1, {
        enabled: true,
      });
    });
    expect(toastMock).toHaveBeenCalledWith(
      expect.objectContaining({
        variant: "success",
        description: "approvalPage.scenarioUpdateSuccess",
      }),
    );
    expect(listApprovalScenariosApi).toHaveBeenCalledTimes(2);
  });
});
