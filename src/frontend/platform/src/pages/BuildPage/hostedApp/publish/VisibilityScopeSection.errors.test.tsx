import { getResourcePermissionContextApi, getResourcePermissionGrantsApi, type ResourcePermissionContext } from "@/controllers/API/permission";
import { showApiError } from "@/controllers/request";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { HostedAppDetail } from "@/controllers/API/hostedApp";
import { VisibilityScopeSection } from "./VisibilityScopeSection";

vi.mock("@/controllers/API/permission", () => ({
  getResourcePermissionContextApi: vi.fn(), getResourcePermissionGrantsApi: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: (request: Promise<unknown>) => request,
  showApiError: vi.fn(),
}));
vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({ PermissionDialog: () => null }));
const app = { app_id: "app-1", name: "Example", state: "online" } as HostedAppDetail;

beforeEach(() => vi.clearAllMocks());
describe("visibility permission request failures", () => {
  it("ends loading and does not fetch grants when context lookup rejects", async () => {
    const error = new Error("context unavailable");
    vi.mocked(getResourcePermissionContextApi).mockRejectedValueOnce(error);
    render(<VisibilityScopeSection app={app} />);
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
    expect(screen.queryByText("hostedApp.visibility.loading")).toBeNull();
    expect(getResourcePermissionGrantsApi).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "hostedApp.visibility.configure" })).toBeDisabled();
  });
  it("ends loading after a grant request rejects", async () => {
    const error = new Error("grants unavailable");
    vi.mocked(getResourcePermissionContextApi).mockResolvedValueOnce({ can_manage_permission: true } as ResourcePermissionContext);
    vi.mocked(getResourcePermissionGrantsApi).mockRejectedValueOnce(error);
    render(<VisibilityScopeSection app={app} />);
    await waitFor(() => expect(showApiError).toHaveBeenCalledWith(error));
    expect(screen.queryByText("hostedApp.visibility.loading")).toBeNull();
    expect(getResourcePermissionGrantsApi).toHaveBeenCalledTimes(1);
  });
});
