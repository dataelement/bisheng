import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import {
  getMessageListApi,
  markMessageReadApi,
} from "~/api/message";
import { NotificationsDialog } from "./NotificationsDialog";

jest.mock("react-i18next", () => ({
  useTranslation: () => ({ i18n: { language: "zh-CN" } }),
}));

jest.mock("~/hooks/useLocalize", () => ({
  __esModule: true,
  default: () => (key: string, vars?: Record<string, string>) => {
    const translations: Record<string, string> = {
      com_notifications_action_request_menu_access: "申请访问菜单「{{target}}」",
      com_notifications_action_approval_task_pending: "提交了「{{target}}」审批申请",
    };
    const template = translations[key];
    if (!template) return key;
    return template.replace("{{target}}", vars?.target ?? "");
  },
}));

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("~/api/message", () => ({
  getMessageListApi: jest.fn(),
  markMessageReadApi: jest.fn(),
  markAllMessageReadApi: jest.fn(),
  deleteMessageApi: jest.fn(),
}));

jest.mock("~/components/ui/Dialog", () => ({
  Dialog: ({ open, children }: { open?: boolean; children: React.ReactNode }) => (open ? <div>{children}</div> : null),
  DialogContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DialogTitle: ({ children }: { children: React.ReactNode }) => <h2>{children}</h2>,
}));

jest.mock("~/components/ui/ExpandableSearchField", () => ({
  ExpandableSearchField: () => null,
}));

jest.mock("~/components/ui/Tabs", () => ({
  Tabs: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsList: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TabsTrigger: ({ children }: { children: React.ReactNode }) => <button type="button">{children}</button>,
  TabsContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock("~/components/ui/Button", () => ({
  Button: ({ children, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button type="button" {...props}>{children}</button>
  ),
}));

jest.mock("~/components/ui/Avatar", () => ({
  Avatar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  AvatarImage: () => null,
  AvatarName: ({ name }: { name?: string }) => <span>{name}</span>,
}));

jest.mock("~/components/ui/Tooltip", () => ({
  TooltipAnchor: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

describe("NotificationsDialog approval jump", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    Object.defineProperty(window, "matchMedia", {
      writable: true,
      value: jest.fn().mockImplementation(() => ({
        matches: false,
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
      })),
    });
    class MockIntersectionObserver {
      observe = jest.fn();
      disconnect = jest.fn();
    }
    (window as any).IntersectionObserver = MockIntersectionObserver;
    (global as any).IntersectionObserver = MockIntersectionObserver;
  });

  it("opens approval center instead of inline approving request messages", async () => {
    jest.mocked(getMessageListApi).mockResolvedValue({
      total: 1,
      data: [{
        id: 501,
        sender: 7,
        sender_name: "Alice",
        message_type: "request",
        action_code: "request_knowledge_space",
        status: "pending",
        is_read: false,
        create_time: "2026-04-27T10:00:00Z",
        update_time: "2026-04-27T10:00:00Z",
        content: [{
          type: "business_url",
          content: "知识空间订阅申请",
          metadata: {
            business_type: "approval_instance_id",
            data: { approval_instance_id: 99 },
          },
        }],
      }],
    });
    jest.mocked(markMessageReadApi).mockResolvedValue({});
    const openApprovalCenter = jest.fn();

    render(<NotificationsDialog open onOpenApprovalCenter={openApprovalCenter} />);

    expect(await screen.findByText("com_notifications_view_approval")).toBeInTheDocument();
    expect(screen.queryByText("com_notifications_accept")).not.toBeInTheDocument();
    expect(screen.queryByText("com_notifications_reject")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("com_notifications_view_approval"));

    await waitFor(() => {
      expect(openApprovalCenter).toHaveBeenCalledWith({
        tab: "my_tasks",
        taskId: null,
        instanceId: 99,
      });
    });
  });

  it("uses scenario-specific PRD copy for later approval nodes", async () => {
    jest.mocked(getMessageListApi).mockResolvedValue({
      total: 1,
      data: [{
        id: 502,
        sender: 7,
        sender_name: "站内信",
        message_type: "notify",
        action_code: "approval_task_pending",
        status: "pending",
        is_read: false,
        create_time: "2026-06-01T10:00:00Z",
        update_time: "2026-06-01T10:00:00Z",
        content: [
          { type: "system_text", content: "approval_task_pending" },
          {
            type: "business_url",
            content: "--知识空间",
            metadata: {
              business_type: "approval_instance_id",
              scenario_code: "menu_access_request",
              data: {
                approval_instance_id: "99",
                business_name: "知识空间",
                scenario_code: "menu_access_request",
              },
            },
          },
        ],
      }],
    });
    jest.mocked(markMessageReadApi).mockResolvedValue({});

    render(<NotificationsDialog open onOpenApprovalCenter={jest.fn()} />);

    expect(await screen.findByText(/申请访问菜单/)).toBeInTheDocument();
    expect(screen.queryByText(/提交了/)).not.toBeInTheDocument();
  });
});
