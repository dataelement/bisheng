import { render, screen, waitFor } from "@testing-library/react";

import { ApprovalCenterDialog } from "./ApprovalCenterDialog";
import {
  getApprovalInstanceDetailApi,
  getMyApprovalTaskDetailApi,
  listMyApprovalRequestsApi,
  listMyApprovalTasksApi,
} from "~/api/approval";

jest.mock("~/hooks/useLocalize", () => ({
  __esModule: true,
  default: () => (key: string) => {
    const map: Record<string, string> = {
      com_approval_field_business_type: "业务类型",
      com_approval_field_space_name_create: "知识库名称",
      com_approval_field_space_level: "知识库层级",
      com_approval_field_auth_type: "加入方式",
      com_approval_field_is_released: "发布到广场",
      com_approval_field_user_group_id: "用户组ID",
      com_approval_field_source_space_name: "源知识库",
      com_approval_field_source_file_name: "源文件",
      com_approval_field_target_space_name: "目标知识库",
      com_approval_field_target_document_title: "目标文档",
      com_approval_business_type_knowledge_space_create: "新建知识库",
      com_approval_business_type_knowledge_space_file_publish: "发布文件",
      com_approval_space_level_team: "团队知识库",
      com_approval_auth_type_approval: "需审批",
      com_approval_value_yes: "是",
    };
    return map[key] ?? key;
  },
}));

const mockShowToast = jest.fn();

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/api/approval", () => ({
  getApprovalInstanceDetailApi: jest.fn(),
  getMyApprovalTaskDetailApi: jest.fn(),
  listMyApprovalRequestsApi: jest.fn(),
  listMyApprovalTasksApi: jest.fn(),
  decideApprovalTaskApi: jest.fn(),
  withdrawApprovalInstanceApi: jest.fn(),
  revokeMenuAccessGrantApi: jest.fn(),
}));

jest.mock("~/components/ui/Dialog", () => ({
  Dialog: ({ open, children }: { open?: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));

describe("ApprovalCenterDialog", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("does not render a resubmit action for rejected requests", async () => {
    jest.mocked(listMyApprovalRequestsApi).mockResolvedValue({
      data: [
        {
          instance_id: 21,
          business_name: "知识库申请",
          status: "rejected",
        },
      ],
      total: 1,
    });
    jest.mocked(getApprovalInstanceDetailApi).mockResolvedValue({
      instance_id: 21,
      business_name: "知识库申请",
      status: "rejected",
      scenario_code: "knowledge_space_subscribe_request",
    } as any);

    render(
      <ApprovalCenterDialog
        open
        onOpenChange={jest.fn()}
        target={{ tab: "my_requests", instanceId: 21 }}
      />,
    );

    await waitFor(() => {
      expect(getApprovalInstanceDetailApi).toHaveBeenCalled();
    });
    expect(screen.queryByText("com_approval_action_resubmit")).toBeNull();
  });

  it("renders Shougang knowledge space create business content with localized labels and values", async () => {
    jest.mocked(listMyApprovalTasksApi).mockResolvedValue({
      data: [
        {
          task_id: 31,
          instance_id: 131,
          business_name: "新建知识库：团队资料",
          status: "pending",
          scenario_code: "knowledge_space_create_request",
        },
      ],
      total: 1,
    });
    jest.mocked(getMyApprovalTaskDetailApi).mockResolvedValue({
      task_id: 31,
      instance_id: 131,
      business_name: "新建知识库：团队资料",
      status: "pending",
      scenario_code: "knowledge_space_create_request",
      detail_snapshot: {
        type: "knowledge_space_create",
        name: "团队资料",
        auth_type: "approval",
        is_released: true,
        space_level: "team",
        user_group_id: 1,
      },
    } as any);

    render(
      <ApprovalCenterDialog
        open
        onOpenChange={jest.fn()}
        target={{ tab: "my_tasks", taskId: 31 }}
      />,
    );

    expect(await screen.findByText("业务类型")).toBeInTheDocument();
    expect(screen.getByText("新建知识库")).toBeInTheDocument();
    expect(screen.getByText("知识库名称")).toBeInTheDocument();
    expect(screen.getByText("团队资料")).toBeInTheDocument();
    expect(screen.getByText("知识库层级")).toBeInTheDocument();
    expect(screen.getByText("团队知识库")).toBeInTheDocument();
    expect(screen.getByText("加入方式")).toBeInTheDocument();
    expect(screen.getByText("需审批")).toBeInTheDocument();
    expect(screen.getByText("发布到广场")).toBeInTheDocument();
    expect(screen.getByText("是")).toBeInTheDocument();
    expect(screen.getByText("用户组ID")).toBeInTheDocument();
    expect(screen.queryByText("type")).not.toBeInTheDocument();
    expect(screen.queryByText("name")).not.toBeInTheDocument();
    expect(screen.queryByText("auth_type")).not.toBeInTheDocument();
    expect(screen.queryByText("space_level")).not.toBeInTheDocument();
    expect(screen.queryByText("is_released")).not.toBeInTheDocument();
  });

  it("renders Shougang file publish business content with names instead of duplicate ID fields", async () => {
    jest.mocked(listMyApprovalRequestsApi).mockResolvedValue({
      data: [
        {
          instance_id: 41,
          business_name: "发布文件：操作手册",
          status: "pending",
          scenario_code: "knowledge_space_file_publish_request",
        },
      ],
      total: 1,
    });
    jest.mocked(getApprovalInstanceDetailApi).mockResolvedValue({
      instance_id: 41,
      business_name: "发布文件：操作手册",
      status: "pending",
      scenario_code: "knowledge_space_file_publish_request",
      detail_snapshot: {
        type: "knowledge_space_file_publish",
        source_space_id: 10,
        source_space_name: "团队知识库",
        source_file_id: 20,
        source_file_name: "操作手册.pdf",
        target_space_id: 30,
        target_space_name: "业务域知识库",
        target_document_id: 40,
        target_document_title: "操作手册",
      },
    } as any);

    render(
      <ApprovalCenterDialog
        open
        onOpenChange={jest.fn()}
        target={{ tab: "my_requests", instanceId: 41 }}
      />,
    );

    expect(await screen.findByText("业务类型")).toBeInTheDocument();
    expect(screen.getByText("发布文件")).toBeInTheDocument();
    expect(screen.getByText("源知识库")).toBeInTheDocument();
    expect(screen.getByText("团队知识库")).toBeInTheDocument();
    expect(screen.getByText("源文件")).toBeInTheDocument();
    expect(screen.getByText("操作手册.pdf")).toBeInTheDocument();
    expect(screen.getByText("目标知识库")).toBeInTheDocument();
    expect(screen.getByText("业务域知识库")).toBeInTheDocument();
    expect(screen.getByText("目标文档")).toBeInTheDocument();
    expect(screen.getByText("操作手册")).toBeInTheDocument();
    expect(screen.queryByText("source_space_id")).not.toBeInTheDocument();
    expect(screen.queryByText("source_file_id")).not.toBeInTheDocument();
    expect(screen.queryByText("target_space_id")).not.toBeInTheDocument();
    expect(screen.queryByText("target_document_id")).not.toBeInTheDocument();
  });

  it("keeps fallback labels for non-Shougang business content", async () => {
    jest.mocked(listMyApprovalRequestsApi).mockResolvedValue({
      data: [
        {
          instance_id: 51,
          business_name: "其他审批",
          status: "pending",
          scenario_code: "custom_request",
        },
      ],
      total: 1,
    });
    jest.mocked(getApprovalInstanceDetailApi).mockResolvedValue({
      instance_id: 51,
      business_name: "其他审批",
      status: "pending",
      scenario_code: "custom_request",
      detail_snapshot: {
        custom_field: "自定义值",
      },
    } as any);

    render(
      <ApprovalCenterDialog
        open
        onOpenChange={jest.fn()}
        target={{ tab: "my_requests", instanceId: 51 }}
      />,
    );

    expect(await screen.findByText("custom_field")).toBeInTheDocument();
    expect(screen.getByText("自定义值")).toBeInTheDocument();
  });
});
