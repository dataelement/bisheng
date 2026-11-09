import { render, screen } from "@testing-library/react";
import { SpaceProcessingPanel } from "./SpaceProcessingPanel";
import { useSpaceProcessingJobs } from "../hooks/useSpaceProcessingJobs";
import type { ProcessingJobRead, ProcessingItemRead } from "~/api/knowledgeProcessing";
jest.mock("~/utils", () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(" ") }));
jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string, values?: Record<string, string | number>) =>
    key + (values ? JSON.stringify(values) : ""),
}));
jest.mock("../hooks/useSpaceProcessingJobs", () => ({ useSpaceProcessingJobs: jest.fn() }));
const empty = {
  history: undefined,
  job: undefined,
  items: undefined,
  available: false,
  open: false,
  show: jest.fn(),
  close: jest.fn(),
  loading: false,
  total: 0,
  page: 1,
  itemPage: 1,
  setPage: jest.fn(),
  setItemPage: jest.fn(),
  select: jest.fn(),
  historyView: jest.fn(),
  selected: false,
  error: false,
  pending: false,
  retrying: false,
  accepted: false,
  retry: jest.fn(),
  refresh: jest.fn(),
};
beforeEach(() =>
  jest
    .mocked(useSpaceProcessingJobs)
    .mockReturnValue(empty as unknown as ReturnType<typeof useSpaceProcessingJobs>),
);
it("uses actual Root state for non-edit viewers without exposing task controls", () => {
  render(<SpaceProcessingPanel spaceId="3" canEdit={false} state={3} />);
  expect(screen.getByText("com_knowledge.processing_jobs.rebuilding")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "com_knowledge.processing_jobs.title" })).toBeNull();
});
it("shows restricted counts and public status/code without rendering item or target identifiers", () => {
  jest.mocked(useSpaceProcessingJobs).mockReturnValue({
    ...empty,
    open: true,
    available: true,
    selected: true,
    job: {
      kind: "file_reprocess",
      state: "partial_failed",
      total_count: 4,
      succeeded_count: 2,
      failed_count: 1,
      pending_count: 1,
      hidden_item_count: 2,
      retryable: true,
    } as ProcessingJobRead,
    items: {
      data: [
        {
          id: "private-item-id",
          file_id: 898989,
          document_id: 787878,
          version_id: 676767,
          state: "failed",
          message: "private item message",
          error_code: 10997,
        } as ProcessingItemRead,
      ],
      total: 1,
    },
  } as ReturnType<typeof useSpaceProcessingJobs>);
  render(<SpaceProcessingPanel spaceId="3" canEdit state={4} />);
  expect(screen.getByText('com_knowledge.processing_jobs.hidden{"0":2}')).toBeTruthy();
  expect(document.body.textContent).toContain(
    'com_knowledge.processing_jobs.error_code{"0":10997}',
  );
  for (const secret of ["private-item-id", "898989", "787878", "676767", "private item message"])
    expect(document.body.textContent).not.toContain(secret);
});
