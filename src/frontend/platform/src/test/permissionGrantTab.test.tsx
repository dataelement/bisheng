import { PermissionGrantTab } from "@/components/bs-comp/permission/PermissionGrantTab";
import { getGrantableRelationModelsApi } from "@/controllers/API/permission";
import { render, screen, waitFor } from "@/test/test-utils";
import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("@/controllers/API/permission", () => ({
  authorizeResource: vi.fn(),
  getGrantableRelationModelsApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => promise),
}));

vi.mock("@/components/bs-ui/button", () => ({
  Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  useToast: () => ({ message: vi.fn() }),
}));

vi.mock("@/components/bs-comp/permission/SubjectSearchUser", () => ({
  SubjectSearchUser: () => <div>user-search</div>,
}));

vi.mock("@/components/bs-comp/permission/SubjectSearchDepartment", () => ({
  SubjectSearchDepartment: () => <div>department-search</div>,
}));

vi.mock("@/components/bs-comp/permission/SubjectSearchUserGroup", () => ({
  SubjectSearchUserGroup: () => <div>user-group-search</div>,
}));

vi.mock("@/components/bs-comp/permission/RelationSelect", () => ({
  RelationSelect: ({ value, options = [] }: { value: string; options?: Array<{ id: string; name: string }> }) => (
    <div>
      <div data-testid="selected-model">{value}</div>
      <div data-testid="relation-options">{options.map((option) => option.name).join("|")}</div>
    </div>
  ),
}));

const mockedGetGrantableRelationModelsApi = vi.mocked(getGrantableRelationModelsApi);

describe("PermissionGrantTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetGrantableRelationModelsApi.mockResolvedValue([
      { id: "owner", name: "所有者", relation: "owner", is_system: true },
      { id: "manager", name: "可管理", relation: "manager", is_system: true },
      { id: "editor", name: "可编辑", relation: "editor", is_system: true },
      { id: "viewer", name: "可查看", relation: "viewer", is_system: true },
    ] as any);
  });

  it("hides owner grants for departments and user groups", async () => {
    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="123"
        onSuccess={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("relation-options")).toHaveTextContent("level.owner");
    });
    expect(screen.getByTestId("selected-model")).toHaveTextContent("owner");

    fireEvent.click(screen.getByRole("button", { name: "subject.department" }));
    await waitFor(() => {
      expect(screen.getByTestId("relation-options")).not.toHaveTextContent("level.owner");
    });
    expect(screen.getByTestId("selected-model")).toHaveTextContent("manager");

    fireEvent.click(screen.getByRole("button", { name: "subject.userGroup" }));
    await waitFor(() => {
      expect(screen.getByTestId("relation-options")).not.toHaveTextContent("level.owner");
    });
    expect(screen.getByTestId("selected-model")).toHaveTextContent("manager");
  });

  it("reuses prefetched grantable relation models without refetching", async () => {
    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="123"
        onSuccess={vi.fn()}
        prefetchedGrantableModels={[
          { id: "viewer", name: "可查看", relation: "viewer", is_system: true },
          { id: "editor", name: "可编辑", relation: "editor", is_system: true },
        ] as any}
        prefetchedGrantableModelsLoaded
        skipGrantableModelsRequest
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("relation-options")).toHaveTextContent("level.viewer");
    });

    expect(mockedGetGrantableRelationModelsApi).not.toHaveBeenCalled();
  });
});
