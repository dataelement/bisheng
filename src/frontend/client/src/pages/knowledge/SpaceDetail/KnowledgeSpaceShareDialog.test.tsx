import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { getGrantableRelationModels } from "~/api/permission";
import { KnowledgeSpaceShareDialog } from "./KnowledgeSpaceShareDialog";

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("~/utils", () => ({
  copyText: jest.fn(),
}));

jest.mock("~/api/permission", () => ({
  getGrantableRelationModels: jest.fn(),
}));

jest.mock("~/components/KnowledgeSpaceMemberManagementPanel", () => ({
  KnowledgeSpaceMemberManagementPanel: () => <div>member-panel</div>,
}));

jest.mock("~/components/permission/PermissionListTab", () => ({
  PermissionListTab: ({ resourceType, resourceId, fixedSubjectType }: any) => (
    <div>{`list:${resourceType}:${resourceId}:${fixedSubjectType}`}</div>
  ),
}));

jest.mock("~/components/permission/PermissionGrantTab", () => ({
  PermissionGrantTab: ({ resourceType, resourceId, fixedSubjectType, includeChildren }: any) => (
    <div>{`grant:${resourceType}:${resourceId}:${fixedSubjectType}:${includeChildren ? "include" : "exclude"}`}</div>
  ),
}));

jest.mock("~/components/ui", () => ({
  Button: ({ children, ...props }: any) => <button {...props}>{children}</button>,
  Checkbox: ({ checked, onCheckedChange }: any) => (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked ? "true" : "false"}
      onClick={() => onCheckedChange?.(!checked)}
    />
  ),
  Dialog: ({ children }: any) => <div>{children}</div>,
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogHeader: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <div>{children}</div>,
  Input: (props: any) => <input {...props} />,
  Tabs: ({ children }: any) => <div>{children}</div>,
  TabsContent: ({ children }: any) => <div>{children}</div>,
  TabsList: ({ children }: any) => <div>{children}</div>,
  TabsTrigger: ({ children }: any) => <button type="button">{children}</button>,
}));

const mockedGetGrantableRelationModels = jest.mocked(getGrantableRelationModels);

describe("KnowledgeSpaceShareDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGetGrantableRelationModels.mockResolvedValue([
      {
        id: "viewer",
        name: "Viewer",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ]);
  });

  it("renders a single permission list tab instance for the active subject type", async () => {
    render(
      <KnowledgeSpaceShareDialog
        open
        onOpenChange={jest.fn()}
        resourceId="space-59"
        resourceName="Space 59"
        showShareTab={false}
        showMembersTab={false}
        showPermissionTab
      />,
    );

    await waitFor(() => {
      expect(mockedGetGrantableRelationModels).toHaveBeenCalledTimes(1);
    });
    expect(screen.getAllByText("list:knowledge_space:space-59:user")).toHaveLength(1);
    expect(screen.queryByText("list:knowledge_space:space-59:department")).not.toBeInTheDocument();
    expect(screen.queryByText("list:knowledge_space:space-59:user_group")).not.toBeInTheDocument();
  });

  it("passes the include-children toggle state into the grant form", async () => {
    render(
      <KnowledgeSpaceShareDialog
        open
        onOpenChange={jest.fn()}
        resourceId="space-59"
        resourceName="Space 59"
        showShareTab={false}
        showMembersTab={false}
        showPermissionTab
      />,
    );

    await waitFor(() => {
      expect(mockedGetGrantableRelationModels).toHaveBeenCalledTimes(1);
    });

    const grantDepartmentTab = screen.getAllByRole("button", {
      name: "com_permission.subject_department",
    }).at(-1);
    expect(grantDepartmentTab).toBeTruthy();
    fireEvent.click(grantDepartmentTab!);
    expect(await screen.findByText("grant:knowledge_space:space-59:department:include")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox"));
    expect(await screen.findByText("grant:knowledge_space:space-59:department:exclude")).toBeInTheDocument();
  });

  it("can manage a file resource with the same grant dialog", async () => {
    render(
      <KnowledgeSpaceShareDialog
        open
        onOpenChange={jest.fn()}
        resourceType="knowledge_file"
        resourceId="file-9"
        resourceName="File 9"
        showShareTab={false}
        showMembersTab={false}
        showPermissionTab
      />,
    );

    await waitFor(() => {
      expect(mockedGetGrantableRelationModels).toHaveBeenCalledWith("knowledge_file", "file-9");
    });
    expect(screen.getByText("list:knowledge_file:file-9:user")).toBeInTheDocument();
    expect(screen.getByText("grant:knowledge_file:file-9:user:include")).toBeInTheDocument();
  });

  it("can manage a folder resource with the same grant dialog", async () => {
    render(
      <KnowledgeSpaceShareDialog
        open
        onOpenChange={jest.fn()}
        resourceType="folder"
        resourceId="folder-9"
        resourceName="Folder 9"
        showShareTab={false}
        showMembersTab={false}
        showPermissionTab
      />,
    );

    await waitFor(() => {
      expect(mockedGetGrantableRelationModels).toHaveBeenCalledWith("folder", "folder-9");
    });
    expect(screen.getByText("list:folder:folder-9:user")).toBeInTheDocument();
    expect(screen.getByText("grant:folder:folder-9:user:include")).toBeInTheDocument();
  });
});
