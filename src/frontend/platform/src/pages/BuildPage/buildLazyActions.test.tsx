import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { userContext } from "@/contexts/userContext";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import { getWorkFlowVersions, changeWorkflowCurrentVersion } from "@/controllers/API/workflow";
import { getHostedAppVersionsApi } from "@/controllers/API/hostedApp";
import { useBuildAppActions } from "./useBuildAppActions";
import CardSelectVersion from "./CardSelectVersion";
import { HostedAppCard } from "./HostedAppCard";

vi.mock("@/contexts/userContext", async () => ({ userContext: (await import("react")).createContext({ user: null }) }));
vi.mock("@/controllers/API/permission", () => ({ getMyResourcePermissionsApi: vi.fn() }));
vi.mock("@/controllers/API/workflow", () => ({ getWorkFlowVersions: vi.fn(), changeWorkflowCurrentVersion: vi.fn() }));
vi.mock("@/controllers/API/hostedApp", () => ({ getHostedAppVersionsApi: vi.fn() }));
vi.mock("@/controllers/request", () => ({ showApiError: vi.fn() }));
vi.mock("@/controllers/managementScope", () => ({ managementRequestScope: () => null }));
vi.mock("./useHostedAppActions", () => ({ useHostedAppActions: () => ({ stopApp: vi.fn(), resumeApp: vi.fn(), deleteApp: vi.fn() }) }));
vi.mock("@/components/bs-comp/formFields/useSelectLabels", () => ({ useSelectLabels: () => ({}) }));
vi.mock("@/components/bs-comp/cardComponent/avatar", () => ({ default: () => null }));
vi.mock("@/components/bs-icons/loading/LoadingState", () => ({ LoadingState: () => <span>loading</span> }));
vi.mock("@/components/bs-comp/cardComponent", () => ({
  default: (props: { headSelecter: React.ReactNode; onMenuOpen: () => void }) => <div>
    {props.headSelecter}<button onClick={props.onMenuOpen}>settings</button>
  </div>,
}));
vi.mock("@bisheng/ui", () => ({
  notification: { open: vi.fn() },
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{children}</button>,
  Tag: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Select: (props: { onOpenChange: (value: boolean) => void; onChange: (id: string) => void; options: { value: string; label: string }[] }) => <div>
    <button onClick={() => props.onOpenChange(true)}>versions</button>
    {props.options.map(option => <button key={option.value} onClick={() => props.onChange(option.value)}>{option.label}</button>)}
  </div>,
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getMyResourcePermissionsApi).mockResolvedValue({ actions: ["visible", "edit"] } as never);
  vi.mocked(getWorkFlowVersions).mockResolvedValue({ data: [{ id: 1, name: "v1", is_current: 1 }, { id: 2, name: "v2", is_current: 0 }], total: 2 });
  vi.mocked(getHostedAppVersionsApi).mockResolvedValue([]);
});

it("loads permissions for only the clicked card and keeps resource types separate", async () => {
  const wrapper = ({ children }: { children: React.ReactNode }) => <userContext.Provider value={{ user: { user_id: 8801, leaf_tenant_id: 101 } } as never}>{children}</userContext.Provider>;
  const { result } = renderHook(useBuildAppActions, { wrapper });
  expect(getMyResourcePermissionsApi).not.toHaveBeenCalled();
  await act(async () => { await result.current.load({ id: "shared-id", flow_type: 10 }); });
  expect(getMyResourcePermissionsApi).toHaveBeenCalledExactlyOnceWith("workflow", "shared-id");
  await act(async () => { await result.current.load({ id: "shared-id", flow_type: 10 }); });
  expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(1);
  await act(async () => { await result.current.load({ id: "shared-id", flow_type: 35 }); });
  expect(getMyResourcePermissionsApi).toHaveBeenLastCalledWith("app", "shared-id");
  expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(2);
});

it("retires an in-flight permission result when the user's tenant changes", async () => {
  let tenant = 101;
  let finish!: (value: never) => void;
  vi.mocked(getMyResourcePermissionsApi).mockImplementationOnce(() => new Promise(resolve => { finish = resolve; }));
  const wrapper = ({ children }: { children: React.ReactNode }) => <userContext.Provider value={{ user: { user_id: 8803, leaf_tenant_id: tenant } } as never}>{children}</userContext.Provider>;
  const { result, rerender } = renderHook(useBuildAppActions, { wrapper });
  let pending!: ReturnType<typeof result.current.load>;
  act(() => { pending = result.current.load({ id: "retired-card", flow_type: 10 }); });
  tenant = 202;
  rerender();
  await act(async () => {
    finish({ actions: ["edit"] } as never);
    expect(await pending).toEqual({ actions: [], hasError: true });
  });
  expect(result.current.actions({ id: "retired-card", flow_type: 10 })).toBeUndefined();
});

it("does not reuse a user's permission cache across tenants", async () => {
  const { result } = renderHook(useBuildAppActions, {
    wrapper: ({ children }) => <userContext.Provider value={{ user: { user_id: 8802, leaf_tenant_id: 101 } } as never}>{children}</userContext.Provider>,
  });
  await act(async () => { await result.current.load({ id: "tenant-cache", flow_type: 10 }); });
  // A fresh provider represents the identity refresh used by tenant switching.
  const second = renderHook(useBuildAppActions, { wrapper: ({ children }) => <userContext.Provider value={{ user: { user_id: 8802, leaf_tenant_id: 202 } } as never}>{children}</userContext.Provider> });
  await act(async () => { await second.result.current.load({ id: "tenant-cache", flow_type: 10 }); });
  expect(getMyResourcePermissionsApi).toHaveBeenCalledTimes(2);
});

it("fetches workflow versions only after opening and switches only after edit is proven", async () => {
  const load = vi.fn().mockResolvedValue({ actions: ["visible", "edit"], hasError: false });
  render(<CardSelectVersion data={{ id: "workflow-a" }} showPop onLoadActions={load} />);
  expect(getWorkFlowVersions).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("versions"));
  await screen.findByText("v2");
  expect(load).toHaveBeenCalledOnce();
  expect(getWorkFlowVersions).toHaveBeenCalledExactlyOnceWith("workflow-a");
  fireEvent.click(screen.getByText("v2"));
  await waitFor(() => expect(changeWorkflowCurrentVersion).toHaveBeenCalledWith({ flow_id: "workflow-a", version_id: 2 }));
});

it("keeps online workflow version browsing read-only", async () => {
  render(<CardSelectVersion data={{ id: "online-flow" }} showPop={false} onLoadActions={vi.fn().mockResolvedValue({ actions: ["edit"], hasError: false })} />);
  fireEvent.click(screen.getByText("versions"));
  await screen.findByText("v2");
  fireEvent.click(screen.getByText("v2"));
  expect(changeWorkflowCurrentVersion).not.toHaveBeenCalled();
});

it("retries workflow version reads after failure without a mount-time request", async () => {
  vi.mocked(getWorkFlowVersions).mockRejectedValueOnce(new Error("unavailable"));
  render(<CardSelectVersion data={{ id: "retry-flow" }} showPop onLoadActions={vi.fn().mockResolvedValue({ actions: ["edit"], hasError: false })} />);
  fireEvent.click(screen.getByText("versions"));
  await waitFor(() => expect(getWorkFlowVersions).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByText("versions"));
  await screen.findByText("v2");
  expect(getWorkFlowVersions).toHaveBeenCalledTimes(2);
});

it("loads hosted versions and permissions only when their controls are clicked", async () => {
  const load = vi.fn().mockResolvedValue({ actions: ["edit"], hasError: false });
  render(<MemoryRouter><HostedAppCard item={{ id: "hosted-a", name: "Hosted", app_state: "stopped" }} currentUser={null} isAdmin={false} onLoadActions={load} onPermission={vi.fn()} onChanged={vi.fn()} /></MemoryRouter>);
  expect(load).not.toHaveBeenCalled();
  expect(getHostedAppVersionsApi).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("settings"));
  expect(load).toHaveBeenCalledTimes(1);
  expect(getHostedAppVersionsApi).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("skills.version"));
  await waitFor(() => expect(getHostedAppVersionsApi).toHaveBeenCalledExactlyOnceWith("hosted-a"));
  expect(load).toHaveBeenCalledTimes(2);
});
