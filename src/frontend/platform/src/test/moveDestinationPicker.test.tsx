import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  knowledgeSpaceApi,
  type CursorPage,
  type KnowledgeSpaceChild,
} from "@/controllers/API/knowledgeSpace";
import { knowledgeFilesApi } from "@/controllers/API/knowledgeFiles";
import {
  precheckMove,
  confirmMove,
  type MoveDestination,
} from "@/controllers/API/knowledgeMove";
import { MoveDestinationPicker } from "@/pages/KnowledgePage/components/MoveDestinationPicker";
import { MoveDialog } from "@/pages/KnowledgePage/components/MoveDialog";

vi.mock("@/controllers/request", () => ({
  default: {},
  showApiError: vi.fn(),
}));
vi.mock("@/controllers/API", () => ({ getKnowledgeDetailApi: vi.fn() }));
vi.mock("@/controllers/managementScope", () => ({
  managementRequestScope: () => 101,
}));
vi.mock("@/controllers/API/knowledgeSpace", () => ({
  knowledgeSpaceApi: {
    listVisibleSpaces: vi.fn(),
    listChildren: vi.fn(),
    listProcessingJobs: vi.fn(),
  },
}));
vi.mock("@/controllers/API/knowledgeFiles", () => ({
  knowledgeFilesApi: { listSpaceFolderParents: vi.fn() },
}));
vi.mock("@/controllers/API/knowledgeMove", () => ({
  precheckMove: vi.fn(),
  confirmMove: vi.fn(),
}));

const scope = {
  identityKey: "move-test",
  tenantId: 101,
  managementTenantId: 101,
  view: "admin" as const,
};
const clients: QueryClient[] = [];
const page = (
  data: KnowledgeSpaceChild[],
  next: string | null = null,
): CursorPage<KnowledgeSpaceChild> => ({
  data,
  has_more: next !== null,
  next_cursor: next,
  page_size: 60,
});
const folder = { id: 7, knowledge_id: 1, file_type: 0, file_name: "Folder A" };
const file = {
  id: 7,
  knowledge_id: 1,
  file_type: 1,
  file_name: "Document.pdf",
};

beforeEach(() => {
  vi.mocked(knowledgeSpaceApi.listVisibleSpaces).mockImplementation(
    async (query) => ({
      data: [
        { id: 1, name: "Department A", space_kind: "department" as const },
        { id: 2, name: "Space B", space_kind: "normal" as const },
      ].filter(
        (space) => !query?.keyword || space.name.includes(query.keyword),
      ),
      has_more: false,
      next_cursor: null,
      page_size: 60,
    }),
  );
  vi.mocked(knowledgeSpaceApi.listChildren).mockImplementation(
    async (spaceId, query) => {
      if (query?.file_type === 0) return page(query.parent_id ? [] : [folder]);
      if (query?.parent_id)
        return page([{ ...file, id: 8, file_name: "Nested.txt" }]);
      return page(
        spaceId === 1 ? [folder, file] : [{ ...file, file_name: "Other.docx" }],
      );
    },
  );
  vi.mocked(knowledgeFilesApi.listSpaceFolderParents).mockResolvedValue([
    { id: 7, file_name: "Folder A" },
  ]);
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
  vi.resetAllMocks();
});
function draw(dialog = false) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: console.warn, error: () => {} },
  });
  clients.push(client);
  function Picker() {
    const [value, setValue] = useState<MoveDestination>({
      spaceId: 1,
      folderId: null,
    });
    return (
      <>
        <MoveDestinationPicker
          scope={scope}
          sourceId={1}
          value={value}
          onChange={setValue}
        />
        <output aria-label="destination">{JSON.stringify(value)}</output>
      </>
    );
  }
  return render(
    <QueryClientProvider client={client}>
      {dialog ? (
        <MoveDialog
          scope={scope}
          spaceId={1}
          parentId={null}
          items={[{ id: 99, type: "file" }]}
          onClose={vi.fn()}
        />
      ) : (
        <Picker />
      )}
    </QueryClientProvider>,
  );
}

it("shows spaces alongside folders and non-selectable files, preserving overlapping IDs", async () => {
  draw();
  expect(
    await screen.findByRole("button", { name: "Department A" }),
  ).toHaveAttribute("aria-current", "location");
  const contents = screen.getByLabelText("workspace.files");
  expect(
    await within(contents).findByRole("button", { name: "Folder A" }),
  ).toBeVisible();
  expect(
    within(contents).getByText("Document.pdf").closest("li"),
  ).toHaveAttribute("aria-disabled", "true");
  expect(
    within(contents).queryByRole("button", { name: "Document.pdf" }),
  ).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Space B" }));
  expect(await within(contents).findByText("Other.docx")).toBeVisible();
  expect(within(contents).queryByText("Document.pdf")).toBeNull();
  expect(screen.getByRole("status", { name: "destination" })).toHaveTextContent(
    '"spaceId":2',
  );
});

it("navigates folders from both columns and returns to the space root", async () => {
  draw();
  const contents = screen.getByLabelText("workspace.files");
  fireEvent.click(
    await within(contents).findByRole("button", { name: "Folder A" }),
  );
  expect(await within(contents).findByText("Nested.txt")).toBeVisible();
  expect(screen.getByRole("status", { name: "destination" })).toHaveTextContent(
    '"folderId":7',
  );
  fireEvent.click(screen.getByRole("button", { name: "move.root" }));
  expect(await within(contents).findByText("Document.pdf")).toBeVisible();
  const tree = screen.getByRole("region", { name: "sidebar.department" });
  fireEvent.click(
    await within(tree).findByRole("button", { name: "Folder A" }),
  );
  expect(await within(contents).findByText("Nested.txt")).toBeVisible();
});

it("searches the space column without changing the selected destination", async () => {
  draw();
  await screen.findByRole("button", { name: "Space B" });
  fireEvent.change(
    screen.getByRole("searchbox", { name: "move.search_spaces" }),
    { target: { value: "Space B" } },
  );
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Department A" })).toBeNull(),
  );
  expect(screen.getByRole("status", { name: "destination" })).toHaveTextContent(
    '"spaceId":1',
  );
  expect(screen.getByText("Document.pdf")).toBeVisible();
  fireEvent.change(
    screen.getByRole("searchbox", { name: "move.search_spaces" }),
    { target: { value: "missing" } },
  );
  expect(await screen.findByText("sidebar.empty")).toBeVisible();
});

it("loads subsequent contents pages and retries a failed page without losing previous rows", async () => {
  vi.mocked(knowledgeSpaceApi.listChildren).mockImplementation(
    async (_spaceId, query) => {
      if (query?.file_type === 0) return page([]);
      if (query?.cursor) throw new Error("Page failed");
      return page([file], "next");
    },
  );
  draw();
  const contents = screen.getByLabelText("workspace.files");
  fireEvent.click(
    await within(contents).findByRole("button", { name: "f118.more_files" }),
  );
  const retry = await within(contents).findByRole("button", { name: "retry" });
  expect(within(contents).getByText("Document.pdf")).toBeVisible();
  vi.mocked(knowledgeSpaceApi.listChildren).mockResolvedValue(
    page([{ ...file, id: 8, file_name: "Page 2.txt" }]),
  );
  fireEvent.click(retry);
  expect(await within(contents).findByText("Page 2.txt")).toBeVisible();
  expect(within(contents).getByText("Document.pdf")).toBeVisible();
});

it("prechecks the chosen folder before submitting the immutable confirmation", async () => {
  vi.mocked(precheckMove).mockResolvedValue({
    confirmation_id: "review-id",
    plan_digest: "digest",
    expires_at: "2030-01-01",
    check_complete: true,
    can_execute: true,
    valid_items: [{ id: 99, type: "file" }],
    invalid_items: [],
    impact: {},
    requires_skip_confirmation: false,
  });
  vi.mocked(confirmMove).mockResolvedValue({
    moved: [{ id: 99, type: "file" }],
    invalid: [],
  });
  draw(true);
  fireEvent.click(
    await within(screen.getByLabelText("workspace.files")).findByRole(
      "button",
      { name: "Folder A" },
    ),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "f118.processing_review_action" }),
  );
  await waitFor(() =>
    expect(precheckMove).toHaveBeenCalledWith(
      1,
      [{ id: 99, type: "file" }],
      { spaceId: 1, folderId: 7 },
      101,
    ),
  );
  fireEvent.click(await screen.findByRole("button", { name: "confirm" }));
  await waitFor(() =>
    expect(confirmMove).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        confirmation_id: "review-id",
        plan_digest: "digest",
        idempotency_key: expect.any(String),
      }),
      101,
    ),
  );
  expect(await screen.findByText("move.completed")).toBeVisible();
});
