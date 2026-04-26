import { PermissionGrantTab } from "@/components/bs-comp/permission/PermissionGrantTab";
import { getGrantableRelationModelsApi, getResourcePermissions } from "@/controllers/API/permission";
import { render, screen, waitFor } from "@/test/test-utils";
import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const subjectSearchUserMock = vi.hoisted(() => vi.fn());
const subjectSearchDepartmentMock = vi.hoisted(() => vi.fn());
const subjectSearchUserGroupMock = vi.hoisted(() => vi.fn());

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

vi.mock("@/controllers/API/permission", () => ({
  authorizeResource: vi.fn(),
  getGrantableRelationModelsApi: vi.fn(),
  getResourcePermissions: vi.fn(),
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
  SubjectSearchUser: (props: any) => {
    subjectSearchUserMock(props);
    return <div data-testid="user-search">{props.disabledIds?.join(",")}</div>;
  },
}));

vi.mock("@/components/bs-comp/permission/SubjectSearchDepartment", () => ({
  SubjectSearchDepartment: (props: any) => {
    subjectSearchDepartmentMock(props);
    return <div data-testid="department-search">{props.disabledIds?.join(",")}</div>;
  },
}));

vi.mock("@/components/bs-comp/permission/SubjectSearchUserGroup", () => ({
  SubjectSearchUserGroup: (props: any) => {
    subjectSearchUserGroupMock(props);
    return <div data-testid="user-group-search">{props.disabledIds?.join(",")}</div>;
  },
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
const mockedGetResourcePermissions = vi.mocked(getResourcePermissions);

describe("PermissionGrantTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetResourcePermissions.mockResolvedValue([]);
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
    expect(screen.getByTestId("selected-model")).toHaveTextContent("viewer");

    fireEvent.click(screen.getByRole("button", { name: "subject.department" }));
    await waitFor(() => {
      expect(screen.getByTestId("relation-options")).not.toHaveTextContent("level.owner");
    });
    expect(screen.getByTestId("selected-model")).toHaveTextContent("viewer");

    fireEvent.click(screen.getByRole("button", { name: "subject.userGroup" }));
    await waitFor(() => {
      expect(screen.getByTestId("relation-options")).not.toHaveTextContent("level.owner");
    });
    expect(screen.getByTestId("selected-model")).toHaveTextContent("viewer");
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

  it("passes already granted subjects into the search components as disabled checked ids", async () => {
    mockedGetResourcePermissions.mockResolvedValue([
      {
        subject_type: "user",
        subject_id: 2,
        subject_name: "Alice",
        relation: "viewer",
      },
      {
        subject_type: "department",
        subject_id: 7,
        subject_name: "研发部",
        relation: "viewer",
        include_children: false,
      },
      {
        subject_type: "user_group",
        subject_id: 9,
        subject_name: "产品组",
        relation: "viewer",
      },
    ] as any);

    render(
      <PermissionGrantTab
        resourceType="knowledge_space"
        resourceId="123"
        onSuccess={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("user-search")).toHaveTextContent("2");
    });

    fireEvent.click(screen.getByRole("button", { name: "subject.department" }));
    await waitFor(() => {
      expect(screen.getByTestId("department-search")).toHaveTextContent("7");
    });

    fireEvent.click(screen.getByRole("button", { name: "subject.userGroup" }));
    await waitFor(() => {
      expect(screen.getByTestId("user-group-search")).toHaveTextContent("9");
    });

    expect(subjectSearchUserMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ disabledIds: [2] }),
    );
    expect(subjectSearchDepartmentMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ disabledIds: [7] }),
    );
    expect(subjectSearchUserGroupMock).toHaveBeenLastCalledWith(
      expect.objectContaining({ disabledIds: [9] }),
    );
  });
});
