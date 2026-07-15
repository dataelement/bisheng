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
  default: () => (key: string) => key,
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
  const originalParent = window.parent;
  const mockParentPostMessage = jest.fn();

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
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: { ...window, postMessage: mockParentPostMessage },
    });
  });

  afterEach(() => {
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: originalParent,
    });
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

  it.each([
    ["qa_expert_invited", null, null],
    ["qa_expert_answered", "42", null],
    ["qa_answer_commented", "42", "77"],
    ["qa_answer_accepted", "99", null],
  ])("posts portal navigate message when clicking a %s notification target", async (actionCode, expectedAnswerId, expectedCommentId) => {
    const businessData: Record<string, string> = { question_id: "12345" };
    if (expectedAnswerId) businessData.answer_id = expectedAnswerId;
    if (expectedCommentId) businessData.comment_id = expectedCommentId;

    jest.mocked(getMessageListApi).mockResolvedValue({
      total: 1,
      data: [{
        id: 601,
        sender: 8,
        sender_name: "Expert",
        message_type: "notify",
        action_code: actionCode,
        status: "approved",
        is_read: false,
        create_time: "2026-04-27T10:00:00Z",
        update_time: "2026-04-27T10:00:00Z",
        content: [
          { type: "user", content: "@Expert", metadata: { user_id: 8 } },
          { type: "system_text", content: actionCode },
          {
            type: "business_url",
            content: "--Test Question",
            metadata: {
              business_type: "qa_question",
              data: businessData,
            },
          },
        ],
      }],
    });
    jest.mocked(markMessageReadApi).mockResolvedValue({});
    const onOpenChange = jest.fn();

    render(<NotificationsDialog open onOpenChange={onOpenChange} />);

    const target = await screen.findByText("Test Question");
    expect(target).toBeInTheDocument();

    fireEvent.click(target);

    await waitFor(() => {
      expect(markMessageReadApi).toHaveBeenCalledWith([601]);
    });
    const expectedPayload: Record<string, string> = {
      type: "shougang-portal:qa-expert-navigate",
      questionId: "12345",
      actionCode,
    };
    if (expectedAnswerId) expectedPayload.answerId = expectedAnswerId;
    if (expectedCommentId) expectedPayload.commentId = expectedCommentId;
    expect(mockParentPostMessage).toHaveBeenCalledWith(expectedPayload, "*");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not post portal navigate message when not embedded in an iframe", async () => {
    Object.defineProperty(window, "parent", {
      configurable: true,
      value: window,
    });

    jest.mocked(getMessageListApi).mockResolvedValue({
      total: 1,
      data: [{
        id: 602,
        sender: 8,
        sender_name: "Expert",
        message_type: "notify",
        action_code: "qa_expert_answered",
        status: "approved",
        is_read: false,
        create_time: "2026-04-27T10:00:00Z",
        update_time: "2026-04-27T10:00:00Z",
        content: [
          { type: "user", content: "@Expert", metadata: { user_id: 8 } },
          { type: "system_text", content: "qa_expert_answered" },
          {
            type: "business_url",
            content: "--Test Question",
            metadata: {
              business_type: "qa_question",
              data: { question_id: "12345" },
            },
          },
        ],
      }],
    });
    jest.mocked(markMessageReadApi).mockResolvedValue({});
    const onOpenChange = jest.fn();

    render(<NotificationsDialog open onOpenChange={onOpenChange} />);

    fireEvent.click(await screen.findByText("Test Question"));

    await waitFor(() => {
      expect(onOpenChange).toHaveBeenCalledWith(false);
    });
    expect(mockParentPostMessage).not.toHaveBeenCalled();
  });

  it("does not navigate when clicking an approved review tag notification target name", async () => {
    const openSpy = jest.spyOn(window, "open").mockImplementation(() => null);
    jest.mocked(getMessageListApi).mockResolvedValue({
      total: 1,
      data: [{
        id: 696,
        sender: 1,
        sender_name: "admin",
        message_type: "notify",
        action_code: "approved_review_tag",
        status: "approved",
        is_read: false,
        create_time: "2026-07-14T10:05:44",
        update_time: "2026-07-14T10:05:44",
        content: [
          { type: "user", content: "@admin", metadata: { user_id: 1 } },
          { type: "system_text", content: "approved_review_tag" },
          {
            type: "business_url",
            content: "--「测试哈哈哈」",
            metadata: {
              business_type: "knowledge_file_id",
              data: {
                knowledge_space_id: "214",
                file_id: "501",
                knowledge_file_id: "501",
                business_id: "501",
                business_name: "「测试哈哈哈」",
                file_name: "report.pdf",
                file_type: "pdf",
              },
            },
          },
        ],
      }],
    });
    jest.mocked(markMessageReadApi).mockResolvedValue({});
    const onOpenChange = jest.fn();

    render(<NotificationsDialog open onOpenChange={onOpenChange} />);

    fireEvent.click(await screen.findByText("「测试哈哈哈」"));

    expect(openSpy).not.toHaveBeenCalled();
    expect(onOpenChange).not.toHaveBeenCalled();
    openSpy.mockRestore();
  });
});
