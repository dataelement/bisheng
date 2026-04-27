import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { decideApprovalRequestApi } from "~/api/approval";
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
  default: () => (key: string) => key,
}));

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: jest.fn() }),
}));

jest.mock("~/api/approval", () => ({
  decideApprovalRequestApi: jest.fn(),
}));

jest.mock("~/api/message", () => ({
  getMessageListApi: jest.fn(),
  markMessageReadApi: jest.fn(),
  markAllMessageReadApi: jest.fn(),
  approveMessageApi: jest.fn(),
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

jest.mock("~/components/ui/Textarea", () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...props} />,
}));

describe("NotificationsDialog department upload approval", () => {
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

  it("requests a knowledge-space file list refresh after approving department upload", async () => {
    jest.mocked(getMessageListApi).mockResolvedValue({
      total: 1,
      data: [{
        id: 501,
        sender: 7,
        sender_name: "Alice",
        message_type: "request",
        action_code: "request_department_knowledge_space_upload",
        status: "pending",
        is_read: false,
        create_time: "2026-04-27T10:00:00Z",
        update_time: "2026-04-27T10:00:00Z",
        content: [{
          type: "business_url",
          content: "部门空间（1个文件）",
          metadata: {
            business_type: "approval_request_id",
            data: { approval_request_id: 99 },
          },
        }],
      }],
    });
    jest.mocked(markMessageReadApi).mockResolvedValue({});
    jest.mocked(decideApprovalRequestApi).mockResolvedValue({
      id: 99,
      request_type: "department_knowledge_space_file_upload",
      status: "finalized",
      review_mode: "first_response_wins",
      space_id: 12,
      department_id: 3,
      parent_folder_id: 45,
      applicant_user_id: 7,
      applicant_user_name: "Alice",
      reviewer_user_ids: [8],
      file_count: 1,
      payload_json: { finalized_file_ids: [88] },
      safety_status: "passed",
    });
    const refreshListener = jest.fn();
    window.addEventListener("knowledge-space-files:refresh", refreshListener);

    try {
      render(<NotificationsDialog open />);

      fireEvent.click(await screen.findByText("com_notifications_accept"));

      await waitFor(() => {
        expect(decideApprovalRequestApi).toHaveBeenCalledWith(99, {
          action: "approve",
          reason: undefined,
        });
      });
      expect(refreshListener).toHaveBeenCalledWith(expect.objectContaining({
        detail: {
          spaceId: 12,
          parentFolderId: 45,
          fileIds: [88],
        },
      }));
    } finally {
      window.removeEventListener("knowledge-space-files:refresh", refreshListener);
    }
  });
});
