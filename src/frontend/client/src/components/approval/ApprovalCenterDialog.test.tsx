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

  it("selects the my-task matching the target instance id when no task id is provided", async () => {
    // Channel/space subscribe approval notifications only carry instance_id (no task_id);
    // the dialog must resolve the correct task from instance_id instead of picking the first.
    jest.mocked(listMyApprovalTasksApi).mockResolvedValue({
      data: [
        { task_id: 901, instance_id: 500, status: "pending", business_name: "频道A" },
        { task_id: 902, instance_id: 777, status: "pending", business_name: "频道B" },
      ],
      total: 2,
    });
    jest.mocked(getMyApprovalTaskDetailApi).mockResolvedValue({
      task_id: 902,
      instance_id: 777,
      status: "pending",
    } as any);

    render(
      <ApprovalCenterDialog
        open
        onOpenChange={jest.fn()}
        target={{ tab: "my_tasks", instanceId: 777 }}
      />,
    );

    await waitFor(() => {
      expect(getMyApprovalTaskDetailApi).toHaveBeenCalledWith(902);
    });
  });
});
