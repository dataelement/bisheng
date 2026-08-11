import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import {
  decideApprovalTaskApi,
  getMyApprovalTaskDetailApi,
  listMyApprovalTasksApi,
  type ApprovalTaskDetail,
  type ApprovalTaskItem,
} from "~/api/approval";

import { ApprovalCenterDialog } from "./ApprovalCenterDialog";
import { FILE_CHANGE_APPROVAL_REFRESH_EVENT } from "~/events/fileChangeApprovalEvents";

const mockShowToast = jest.fn();

jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: mockShowToast }),
}));

jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
}));

jest.mock("~/api/approval", () => {
  const actual = jest.requireActual("~/api/approval");
  return {
    ...actual,
    decideApprovalTaskApi: jest.fn(),
    getApprovalInstanceDetailApi: jest.fn(),
    getMyApprovalTaskDetailApi: jest.fn(),
    listMyApprovalRequestsApi: jest.fn().mockResolvedValue({ data: [], total: 0 }),
    listMyApprovalTasksApi: jest.fn(),
  };
});

const mockedDecide = decideApprovalTaskApi as jest.MockedFunction<typeof decideApprovalTaskApi>;
const mockedGetTask = getMyApprovalTaskDetailApi as jest.MockedFunction<typeof getMyApprovalTaskDetailApi>;
const mockedListTasks = listMyApprovalTasksApi as jest.MockedFunction<typeof listMyApprovalTasksApi>;

function task(taskId: number, status = "pending"): ApprovalTaskItem {
  return {
    task_id: taskId,
    instance_id: taskId + 100,
    scenario_code: "knowledge_space_file_change_request",
    business_name: `file-${taskId}.pdf`,
    applicant_user_name: "Ada",
    status,
  };
}

function detail(item: ApprovalTaskItem): ApprovalTaskDetail {
  return {
    ...item,
    payload_snapshot: { space_id: 101 },
    business_status_projection: {
      status: "parse_failed",
      failure_reason: "parser unavailable",
    },
  };
}

describe("ApprovalCenterDialog F046 interactions", () => {
  beforeEach(() => {
    mockedDecide.mockReset();
    mockedGetTask.mockReset();
    mockedListTasks.mockReset();
  });

  it("keeps pending_me after a decision and selects the next pending task", async () => {
    const first = task(1);
    const next = task(2);
    mockedListTasks
      .mockResolvedValueOnce({ data: [first, next], total: 2 })
      .mockResolvedValueOnce({ data: [next], total: 1 });
    mockedGetTask.mockImplementation(async (taskId) => detail(taskId === 1 ? first : next));
    mockedDecide.mockResolvedValue(detail({ ...first, status: "approved" }));

    render(<ApprovalCenterDialog open onOpenChange={jest.fn()} />);

    expect((await screen.findAllByText("file-1.pdf")).length).toBeGreaterThan(0);
    fireEvent.click(await screen.findByText("com_approval_action_approve"));

    await waitFor(() => expect(mockedDecide).toHaveBeenCalledWith(1, expect.any(Object)));
    await waitFor(() => expect(mockedGetTask).toHaveBeenLastCalledWith(2));
    expect(screen.queryAllByText("file-1.pdf")).toHaveLength(0);
    expect(screen.getAllByText("file-2.pdf").length).toBeGreaterThan(0);
    expect(screen.getByText("com_approval_task_filter_pending").className).toContain("font-medium");
    expect(screen.getByText("com_knowledge.file_change_status_parse_failed")).toBeTruthy();
    expect(screen.getByText("parser unavailable")).toBeTruthy();
  });

  it("dispatches a targeted formal-list refresh after a successful F046 decision", async () => {
    const only = task(1);
    mockedListTasks
      .mockResolvedValueOnce({ data: [only], total: 1 })
      .mockResolvedValueOnce({ data: [], total: 0 });
    mockedGetTask.mockResolvedValue(detail(only));
    mockedDecide.mockResolvedValue(detail({ ...only, status: "approved" }));
    const refresh = jest.fn();
    window.addEventListener(FILE_CHANGE_APPROVAL_REFRESH_EVENT, refresh);

    render(<ApprovalCenterDialog open onOpenChange={jest.fn()} />);
    fireEvent.click(await screen.findByText("com_approval_action_approve"));

    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect((refresh.mock.calls[0][0] as CustomEvent).detail).toEqual({ spaceId: 101 });
    window.removeEventListener(FILE_CHANGE_APPROVAL_REFRESH_EVENT, refresh);
  });

  it("shows the pending empty state after deciding the last task", async () => {
    const only = task(1);
    mockedListTasks
      .mockResolvedValueOnce({ data: [only], total: 1 })
      .mockResolvedValueOnce({ data: [], total: 0 });
    mockedGetTask.mockResolvedValue(detail(only));
    mockedDecide.mockResolvedValue(detail({ ...only, status: "approved" }));

    render(<ApprovalCenterDialog open onOpenChange={jest.fn()} />);
    fireEvent.click(await screen.findByText("com_approval_action_approve"));

    await waitFor(() => expect(mockedDecide).toHaveBeenCalledWith(1, expect.any(Object)));
    expect(await screen.findByText("com_approval_empty_list")).toBeTruthy();
    expect(screen.queryByText("com_approval_task_filter_processed")).toBeTruthy();
    expect(screen.getByText("com_approval_task_filter_pending").className).toContain("font-medium");
  });

  it("does not request a former approver's known task id when it is absent from the visible list", async () => {
    const visible = task(2);
    mockedListTasks.mockResolvedValue({ data: [visible], total: 1 });
    mockedGetTask.mockResolvedValue(detail(visible));

    render(
      <ApprovalCenterDialog
        open
        onOpenChange={jest.fn()}
        target={{ tab: "my_tasks", taskId: 999 }}
      />,
    );

    await waitFor(() => expect(mockedGetTask).toHaveBeenCalledWith(2));
    expect(mockedGetTask).not.toHaveBeenCalledWith(999);
    expect(screen.queryByText("file-999.pdf")).toBeNull();
  });

  it("renders file change business fields without internal snapshot keys or values", async () => {
    const only = task(1);
    mockedListTasks.mockResolvedValue({ data: [only], total: 1 });
    mockedGetTask.mockResolvedValue({
      ...detail(only),
      detail_snapshot: {
        change_request_id: 2,
        resource_type: "staged_upload",
        resource_name: "information_source.xlsx",
        action: "upload",
        action_label: "RAW_UPLOAD_LABEL",
        change: {
          relative_path: "reports/information_source.xlsx",
        },
      },
    });

    render(<ApprovalCenterDialog open onOpenChange={jest.fn()} />);

    expect(await screen.findByText("com_knowledge.file_change_action")).toBeTruthy();
    expect(screen.getByText("com_knowledge.file_change_action_upload")).toBeTruthy();
    expect(screen.getByText("com_knowledge.file_name")).toBeTruthy();
    expect(screen.getByText("information_source.xlsx")).toBeTruthy();
    expect(screen.getByText("reports/information_source.xlsx")).toBeTruthy();
    expect(screen.queryByText("change_request_id")).toBeNull();
    expect(screen.queryByText("resource_type")).toBeNull();
    expect(screen.queryByText("staged_upload")).toBeNull();
    expect(screen.queryByText("RAW_UPLOAD_LABEL")).toBeNull();
    expect(screen.queryByText("[object Object]")).toBeNull();
  });
});
