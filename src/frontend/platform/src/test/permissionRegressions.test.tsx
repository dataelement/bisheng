import type { ReactNode } from "react";

import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
import RolesAndPermissions from "@/pages/SystemPage/components/RolesAndPermissions";
import {
  createRelationModelApi,
  getApplicationPermissionTemplateApi,
  getGrantableRelationModelsApi,
  getKnowledgeLibraryPermissionTemplateApi,
  getKnowledgeSpacePermissionTemplateApi,
  getRebacSchemaApi,
  getRelationModelsApi,
  getToolPermissionTemplateApi,
} from "@/controllers/API/permission";
import { darkContext } from "@/contexts/darkContext";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { fireEvent, render, screen, waitFor } from "@/test/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/bs-comp/permission/PermissionListTab", () => ({
  PermissionListTab: ({
    resourceType,
    resourceId,
    refreshKey,
  }: {
    resourceType: string;
    resourceId: string;
    refreshKey?: number;
  }) => (
    <div>{`list:${resourceType}:${resourceId}:${refreshKey ?? 0}`}</div>
  ),
}));

vi.mock("@/components/bs-comp/permission/PermissionGrantTab", () => ({
  PermissionGrantTab: ({
    resourceType,
    resourceId,
    onSuccess,
  }: {
    resourceType: string;
    resourceId: string;
    onSuccess: () => void;
  }) => (
    <div>
      <div>{`grant:${resourceType}:${resourceId}`}</div>
      <button type="button" onClick={onSuccess}>grant-success</button>
    </div>
  ),
}));

vi.mock("@/pages/SystemPage/components/Roles", () => ({
  default: () => <div>roles-panel</div>,
}));

vi.mock("@/components/bs-ui/tabs", () => ({
  Tabs: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({
    children,
    disabled,
  }: {
    children: ReactNode;
    disabled?: boolean;
    value?: string;
  }) => (
    <button type="button" role="tab" disabled={disabled}>
      {children}
    </button>
  ),
  TabsContent: ({ children }: { children: ReactNode; value?: string }) => <div>{children}</div>,
}));

vi.mock("@/controllers/API/permission", () => ({
  createRelationModelApi: vi.fn(),
  deleteRelationModelApi: vi.fn(),
  getApplicationPermissionTemplateApi: vi.fn(),
  getGrantableRelationModelsApi: vi.fn(),
  getKnowledgeLibraryPermissionTemplateApi: vi.fn(),
  getKnowledgeSpacePermissionTemplateApi: vi.fn(),
  getRebacSchemaApi: vi.fn(),
  getRelationModelsApi: vi.fn(),
  getToolPermissionTemplateApi: vi.fn(),
  updateRelationModelApi: vi.fn(),
}));

vi.mock("@/controllers/request", () => ({
  captureAndAlertRequestErrorHoc: vi.fn((promise: Promise<unknown>) => Promise.resolve(promise)),
}));

vi.mock("@/components/bs-ui/toast/use-toast", () => ({
  message: vi.fn(),
}));

const mockedGetApplicationPermissionTemplateApi = vi.mocked(getApplicationPermissionTemplateApi);
const mockedCreateRelationModelApi = vi.mocked(createRelationModelApi);
const mockedGetGrantableRelationModelsApi = vi.mocked(getGrantableRelationModelsApi);
const mockedGetKnowledgeLibraryPermissionTemplateApi = vi.mocked(getKnowledgeLibraryPermissionTemplateApi);
const mockedGetRebacSchemaApi = vi.mocked(getRebacSchemaApi);
const mockedGetRelationModelsApi = vi.mocked(getRelationModelsApi);
const mockedGetKnowledgeSpacePermissionTemplateApi = vi.mocked(getKnowledgeSpacePermissionTemplateApi);
const mockedGetToolPermissionTemplateApi = vi.mocked(getToolPermissionTemplateApi);

const adminUser = {
  user_id: 1,
  user_name: "admin",
  role: "admin",
  web_menu: ["sys"],
  avatar: "",
};

function renderAsAdmin(ui: ReactNode) {
  return render(
    <darkContext.Provider value={{ dark: false, setDark: vi.fn() } as any}>
      <locationContext.Provider
        value={{
          current: [""],
          setCurrent: vi.fn(),
          isStackedOpen: true,
          setIsStackedOpen: vi.fn(),
          showSideBar: true,
          setShowSideBar: vi.fn(),
          extraNavigation: { title: "" },
          setExtraNavigation: vi.fn(),
          extraComponent: null,
          setExtraComponent: vi.fn(),
          appConfig: { multiTenantEnabled: false, noFace: true },
          reloadConfig: vi.fn(),
        } as any}
      >
        <userContext.Provider
          value={{
            user: adminUser,
            setUser: vi.fn(),
            savedComponents: [],
            addSavedComponent: vi.fn(),
            checkComponentsName: vi.fn(),
            delComponent: vi.fn(),
          } as any}
        >
          {ui}
        </userContext.Provider>
      </locationContext.Provider>
    </darkContext.Provider>,
  );
}

async function openRebacTab() {
  renderAsAdmin(<RolesAndPermissions />);
  await screen.findByText("system.relationModelSelectTemplate");
}

describe("Permission dialog regressions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedGetGrantableRelationModelsApi.mockResolvedValue([
      {
        id: "viewer",
        name: "可查看",
        relation: "viewer",
        permissions: [],
        is_system: true,
      },
    ] as any);
  });

  it("renders only list and grant tabs after removing the dead share tab", () => {
    renderAsAdmin(
      <PermissionDialog
        open
        onOpenChange={() => {}}
        resourceType="knowledge_space"
        resourceId="1"
        resourceName="KB"
      />,
    );

    expect(screen.getByText("dialog.tabList")).toBeInTheDocument();
    expect(screen.getByText("dialog.tabGrant")).toBeInTheDocument();
    expect(screen.queryByText("dialog.tabShare")).not.toBeInTheDocument();
  });

  it("loads grantable relation models once when the dialog opens", async () => {
    renderAsAdmin(
      <PermissionDialog
        open
        onOpenChange={() => {}}
        resourceType="knowledge_space"
        resourceId="1"
        resourceName="KB"
      />,
    );

    await waitFor(() => {
      expect(mockedGetGrantableRelationModelsApi).toHaveBeenCalledTimes(1);
    });
    expect(mockedGetGrantableRelationModelsApi).toHaveBeenCalledWith("knowledge_space", "1");
  });

  it("refreshes the permission list after a successful grant action", () => {
    renderAsAdmin(
      <PermissionDialog
        open
        onOpenChange={() => {}}
        resourceType="knowledge_space"
        resourceId="1"
        resourceName="KB"
      />,
    );

    expect(screen.getByText("list:knowledge_space:1:0")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "grant-success" }));

    expect(screen.getByText("list:knowledge_space:1:1")).toBeInTheDocument();
  });
});

describe("Relation model regressions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockedCreateRelationModelApi.mockResolvedValue({ id: "custom_new" } as any);
    mockedGetRebacSchemaApi.mockResolvedValue({
      schema_version: "1",
      model_version: "1",
      types: [
        {
          type: "knowledge_space",
          relations: ["can_read", "can_edit", "can_manage", "can_delete"],
        },
      ],
    } as any);
    mockedGetKnowledgeLibraryPermissionTemplateApi.mockResolvedValue({
      title: "知识库模块",
      columns: [
        {
          title: "",
          items: [
            { id: "view_kb", label: "查看知识库", relation: "can_read" },
          ],
        },
      ],
    } as any);
    mockedGetApplicationPermissionTemplateApi.mockResolvedValue({
      title: "应用/工作流模块",
      columns: [
        {
          title: "",
          items: [
            { id: "use_app", label: "使用应用", relation: "can_read" },
          ],
        },
      ],
    } as any);
    mockedGetToolPermissionTemplateApi.mockResolvedValue({
      title: "工具模块",
      columns: [
        {
          title: "",
          items: [
            { id: "view_tool", label: "查看工具", relation: "can_read" },
          ],
        },
      ],
    } as any);
  });

  it("keeps explicitly emptied relation-model permissions unchecked after reload", async () => {
    mockedGetRelationModelsApi.mockResolvedValue([
      {
        id: "custom_empty",
        name: "空模型",
        relation: "viewer",
        grant_tier: "usage",
        permissions: [],
        permissions_explicit: true,
        is_system: false,
      },
    ] as any);
    mockedGetKnowledgeSpacePermissionTemplateApi.mockResolvedValue({
      title: "知识空间模块",
      columns: [
        {
          title: "空间级",
          items: [
            { id: "view_space", label: "查看空间", relation: "can_read" },
          ],
        },
      ],
    } as any);

    await openRebacTab();

    await waitFor(() => {
      expect(screen.getByRole("combobox")).toHaveTextContent("空模型");
    });

    const checkboxes = screen.getAllByRole("checkbox");
    expect(checkboxes.length).toBeGreaterThan(0);
    checkboxes.forEach((checkbox) => {
      expect(checkbox).not.toBeChecked();
    });
  });

  it("shows custom relation model names without relation suffixes", async () => {
    mockedGetRelationModelsApi.mockResolvedValue([
      {
        id: "custom_plain_name",
        name: "新关系测试",
        relation: "viewer",
        grant_tier: "usage",
        permissions: [],
        permissions_explicit: true,
        is_system: false,
      },
    ] as any);

    await openRebacTab();

    await waitFor(() => {
      expect(screen.getByRole("combobox")).toHaveTextContent("新关系测试");
    });
    expect(screen.getByRole("combobox")).not.toHaveTextContent("新关系测试（");
  });

  it("blocks creating relation models with duplicate names", async () => {
    mockedGetRelationModelsApi.mockResolvedValue([
      {
        id: "custom_existing",
        name: "新关系测试",
        relation: "viewer",
        grant_tier: "usage",
        permissions: [],
        permissions_explicit: true,
        is_system: false,
      },
    ] as any);

    await openRebacTab();

    fireEvent.click(screen.getByRole("button", { name: "system.relationModelCreateButton" }));
    fireEvent.change(
      screen.getByPlaceholderText("system.relationModelNamePlaceholder"),
      { target: { value: " 新关系测试 " } },
    );

    expect(screen.getByText("system.relationModelNameExists")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "confirmButton" })).toBeDisabled();
    expect(mockedCreateRelationModelApi).not.toHaveBeenCalled();
  });

  it("shows relation-model template editing guidance before the selector", async () => {
    mockedGetRelationModelsApi.mockResolvedValue([
      {
        id: "viewer",
        name: "可查看",
        relation: "viewer",
        grant_tier: "usage",
        permissions: [],
        permissions_explicit: false,
        is_system: true,
      },
    ] as any);
    mockedGetKnowledgeSpacePermissionTemplateApi.mockResolvedValue({
      title: "知识空间模块",
      columns: [
        {
          title: "空间级",
          items: [
            { id: "view_space", label: "查看空间", relation: "can_read" },
          ],
        },
      ],
    } as any);

    await openRebacTab();

    expect(screen.getByText("system.relationModelSelectTemplateHint")).toBeInTheDocument();
  });

  it("renders the knowledge-space section from the backend template source of truth", async () => {
    mockedGetRelationModelsApi.mockResolvedValue([
      {
        id: "owner",
        name: "所有者",
        relation: "owner",
        grant_tier: "owner",
        permissions: [],
        permissions_explicit: false,
        is_system: true,
      },
    ] as any);
    mockedGetKnowledgeSpacePermissionTemplateApi.mockResolvedValue({
      title: "后端覆盖模板",
      columns: [
        {
          title: "空间级",
          items: [
            { id: "backend_view_space", label: "后端查看空间", relation: "can_read" },
          ],
        },
      ],
    } as any);

    await openRebacTab();

    expect(await screen.findByText("后端覆盖模板")).toBeInTheDocument();
    expect(screen.getByText("后端查看空间")).toBeInTheDocument();
  });

  it("renders the knowledge-library section from the backend template source of truth", async () => {
    mockedGetRelationModelsApi.mockResolvedValue([
      {
        id: "owner",
        name: "所有者",
        relation: "owner",
        grant_tier: "owner",
        permissions: [],
        permissions_explicit: false,
        is_system: true,
      },
    ] as any);
    mockedGetKnowledgeSpacePermissionTemplateApi.mockResolvedValue({
      title: "知识空间模块",
      columns: [
        {
          title: "空间级",
          items: [
            { id: "view_space", label: "查看空间", relation: "can_read" },
          ],
        },
      ],
    } as any);
    mockedGetKnowledgeLibraryPermissionTemplateApi.mockResolvedValue({
      title: "后端知识库模板",
      columns: [
        {
          title: "",
          items: [
            { id: "backend_use_kb", label: "后端使用知识库", relation: "can_read" },
          ],
        },
      ],
    } as any);

    await openRebacTab();

    expect(await screen.findByText("后端知识库模板")).toBeInTheDocument();
    expect(screen.getByText("后端使用知识库")).toBeInTheDocument();
  });

  it("renders the tool section from the backend template source of truth", async () => {
    mockedGetRelationModelsApi.mockResolvedValue([
      {
        id: "owner",
        name: "所有者",
        relation: "owner",
        grant_tier: "owner",
        permissions: [],
        permissions_explicit: false,
        is_system: true,
      },
    ] as any);
    mockedGetKnowledgeSpacePermissionTemplateApi.mockResolvedValue({
      title: "知识空间模块",
      columns: [
        {
          title: "空间级",
          items: [
            { id: "view_space", label: "查看空间", relation: "can_read" },
          ],
        },
      ],
    } as any);
    mockedGetKnowledgeLibraryPermissionTemplateApi.mockResolvedValue({
      title: "知识库模块",
      columns: [
        {
          title: "",
          items: [
            { id: "view_kb", label: "查看知识库", relation: "can_read" },
          ],
        },
      ],
    } as any);
    mockedGetToolPermissionTemplateApi.mockResolvedValue({
      title: "后端工具模板",
      columns: [
        {
          title: "",
          items: [
            { id: "backend_edit_tool", label: "后端编辑工具", relation: "can_edit" },
          ],
        },
      ],
    } as any);

    await openRebacTab();

    expect(await screen.findByText("后端工具模板")).toBeInTheDocument();
    expect(screen.getByText("后端编辑工具")).toBeInTheDocument();
  });
});
