import { PermissionListTab } from "@/components/bs-comp/permission/PermissionListTab";
import { getDepartmentTreeApi } from "@/controllers/API/department";
import {
  getGrantableRelationModelsApi,
  getResourcePermissions,
} from "@/controllers/API/permission";
import { render, screen, waitFor } from "@/test/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/controllers/API/department", () => ({
  getDepartmentTreeApi: vi.fn(),
}));

vi.mock("@/controllers/API/permission", () => ({
  authorizeResource: vi.fn(),
  getGrantableRelationModelsApi: vi.fn(),
  getResourcePermissions: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ message: vi.fn() }),
}));

vi.mock("@/components/bs-comp/permission/RelationSelect", () => ({
  RelationSelect: ({ value }: { value: string }) => <span>{value}</span>,
}));

const mockedGetDepartmentTreeApi = vi.mocked(getDepartmentTreeApi);
const mockedGetGrantableRelationModelsApi = vi.mocked(getGrantableRelationModelsApi);
const mockedGetResourcePermissions = vi.mocked(getResourcePermissions);

describe("PermissionListTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetDepartmentTreeApi.mockResolvedValue([]);
    mockedGetGrantableRelationModelsApi.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ] as any);
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "viewer",
        model_id: "viewer",
        model_name: "Viewer",
      },
    ] as any);
  });

  it("does not reload grantable relation models when permission entries load", async () => {
    render(
      <PermissionListTab
        resourceType="knowledge_space"
        resourceId="3215"
        refreshKey={0}
      />,
    );

    await screen.findByText("Alice");

    await waitFor(() => {
      expect(mockedGetResourcePermissions).toHaveBeenCalledTimes(1);
    });
    expect(mockedGetGrantableRelationModelsApi).toHaveBeenCalledTimes(1);
    expect(mockedGetGrantableRelationModelsApi).toHaveBeenCalledWith(
      "knowledge_space",
      "3215",
    );
  });
});
