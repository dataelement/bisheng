import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApprovalCenterDialog } from "./ApprovalCenterDialog";
import {
  getApprovalInstanceDetailApi,
  listMyApprovalRequestsApi,
  resubmitApprovalInstanceApi,
} from "~/api/approval";

jest.mock("~/hooks/useLocalize", () => ({
  __esModule: true,
  default: () => (key: string) => key,
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
  resubmitApprovalInstanceApi: jest.fn(),
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

  it("shows a resubmit action for rejected requests and refreshes detail after click", async () => {
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
    jest.mocked(getApprovalInstanceDetailApi)
      .mockResolvedValueOnce({
        instance_id: 21,
        business_name: "知识库申请",
        status: "rejected",
        scenario_code: "knowledge_space_subscribe_request",
      } as any)
      .mockResolvedValueOnce({
        instance_id: 21,
        business_name: "知识库申请",
        status: "pending",
        scenario_code: "knowledge_space_subscribe_request",
      } as any);
    jest.mocked(resubmitApprovalInstanceApi).mockResolvedValue({
      instance_id: 21,
      status: "pending",
      scenario_code: "knowledge_space_subscribe_request",
    } as any);

    render(
      <ApprovalCenterDialog
        open
        onOpenChange={jest.fn()}
        target={{ tab: "my_requests", instanceId: 21 }}
      />,
    );

    const resubmitButton = await screen.findByText("com_approval_action_resubmit");
    fireEvent.click(resubmitButton);

    await waitFor(() => {
      expect(resubmitApprovalInstanceApi).toHaveBeenCalledWith(21, {});
    });
    await waitFor(() => {
      expect(mockShowToast).toHaveBeenCalledWith({
        message: "com_approval_toast_success",
        severity: "success",
      });
    });
    expect(getApprovalInstanceDetailApi).toHaveBeenCalledTimes(2);
  });
});
