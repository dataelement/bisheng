import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceFileUploadPanel } from "@/pages/KnowledgePage/components/SpaceFileUploadPanel";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { uploadSettings } from "./uploadWizardFixtures";

const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  delete: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: mocks,
  showApiError: mocks.error,
}));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({
    appConfig: { enableEtl4lm: true, enableMediaUpload: true },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
  KnowledgeTooltip: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/PreviewFile", () => ({
  default: () => <aside>original-preview</aside>,
}));
vi.mock("@/pages/KnowledgePage/components/PreviewParagraph", () => ({
  default: (props: {
    chunks: { text: string; chunkIndex: number }[];
    edit: boolean;
    onChange: (index: number, text: string) => void;
  }) => (
    <div>
      {props.chunks.map((chunk) => (
        <div key={chunk.chunkIndex}>
          <span>{chunk.text}</span>
          {props.edit && (
            <button
              onClick={() => props.onChange(chunk.chunkIndex, "edited chunk")}
            >
              edit-chunk
            </button>
          )}
        </div>
      ))}
    </div>
  ),
}));
const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const element = (value: KnowledgeQueryScope) => (
    <MemoryRouter>
      <QueryClientProvider client={client}>
        <SpaceFileUploadPanel scope={value} spaceId={7} parentId={9} />
      </QueryClientProvider>
    </MemoryRouter>
  );
  const result = render(element(scope));
  return {
    ...result,
    update: (value: KnowledgeQueryScope) => result.rerender(element(value)),
  };
}
async function drop() {
  await act(async () =>
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [new File(["content"], "report.md")] },
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "nextStep" })).toBeEnabled(),
  );
}
const registers = () =>
  mocks.post.mock.calls.filter(([url]) => url.endsWith("/files"));
const previews = () =>
  mocks.post.mock.calls.filter(([url]) => url.endsWith("/previews"));
const preview = (revision = 0, text = "original chunk") => ({
  preview_id: "b".repeat(32),
  status: "completed",
  revision,
  data: {
    file_url: "/tmp/report.md",
    parse_type: "local",
    partitions: {},
    chunks: [{ text, metadata: { chunk_index: 0 } }],
  },
});
beforeEach(() => {
  vi.resetAllMocks();
  mocks.get.mockImplementation(async (url: string) => {
    if (url.endsWith("/upload-settings")) {
      const value = uploadSettings();
      value.effective_defaults.document.split_mode = "custom";
      value.effective_defaults.document.separator = ["\\n"];
      return value;
    }
    if (url.includes("/previews/")) return preview();
    throw new Error(`unexpected read ${url}`);
  });
  mocks.post.mockImplementation(async (url: string) => {
    if (url.endsWith("/uploads"))
      return {
        file_path: "tmp/report.md",
        upload_id: "a".repeat(32),
        repeat: false,
      };
    if (url.endsWith("/previews")) return { preview_id: "b".repeat(32) };
    if (url.endsWith("/files"))
      return [{ id: 81, knowledge_id: 7, file_name: "report.md", status: 2 }];
    throw new Error(`unexpected write ${url}`);
  });
  mocks.put.mockResolvedValue(preview(1, "edited chunk"));
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
it("loads effective rules for the actual folder eagerly and stages without processing", async () => {
  mount();
  await drop();
  expect(mocks.get).toHaveBeenCalledExactlyOnceWith(
    "/api/v1/knowledge/space/7/files/upload-settings",
    { params: { parent_id: 9 }, signal: expect.any(AbortSignal) },
  );
  expect(registers()).toHaveLength(0);
  expect(previews()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  expect(
    await screen.findByRole("spinbutton", { name: "splitLength" }),
  ).toHaveValue(300);
  expect(screen.getByRole("spinbutton", { name: "chunkOverlap" })).toHaveValue(
    0,
  );
  expect(
    screen.getByRole("checkbox", { name: "keepImages" }),
  ).not.toBeChecked();
});
it("submits the same manual rule and edited preview revision only after comparison confirmation", async () => {
  mount();
  await drop();
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  fireEvent.change(
    await screen.findByRole("spinbutton", { name: "splitLength" }),
    { target: { value: "456" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  await screen.findByText("original-preview");
  fireEvent.click(await screen.findByRole("button", { name: "edit-chunk" }));
  await screen.findByText("edited chunk");
  expect(registers()).toHaveLength(0);
  expect(mocks.put.mock.calls[0]).toEqual([
    `/api/v1/knowledge/space/7/uploads/${"a".repeat(32)}/previews/${"b".repeat(32)}/chunks/0`,
    { text: "edited chunk", bbox: "", expected_revision: 0 },
    { signal: expect.any(AbortSignal) },
  ]);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "nextStep" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  await waitFor(() => expect(registers()).toHaveLength(1));
  const body = registers()[0][1];
  expect(body.overrides.document.chunk_size).toBe(456);
  expect(body.upload_context.items[0]).toMatchObject({
    upload_id: "a".repeat(32),
    preview_id: "b".repeat(32),
    expected_revision: 1,
  });
  expect(body.upload_context.items[0].overrides).toEqual(
    previews()[0][1].overrides,
  );
});
it("keeps manual changes when returning to strategy, and direct upload deliberately uses space defaults", async () => {
  mount();
  await drop();
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  fireEvent.change(
    await screen.findByRole("spinbutton", { name: "splitLength" }),
    { target: { value: "456" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "previousStep" }));
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  expect(
    await screen.findByRole("spinbutton", { name: "splitLength" }),
  ).toHaveValue(456);
  fireEvent.click(screen.getByRole("button", { name: "previousStep" }));
  fireEvent.click(screen.getByRole("button", { name: "uploadDirectly" }));
  await waitFor(() => expect(registers()).toHaveLength(1));
  expect(registers()[0][1].overrides.document.chunk_size).toBe(300);
  expect(registers()[0][1].upload_context.mode).toBe("direct");
  expect(previews()).toHaveLength(0);
});
it("blocks both exits on a defaults read failure and retries the actual request", async () => {
  const failure = new Error("defaults failed");
  mocks.get.mockRejectedValueOnce(failure);
  mount();
  await screen.findByText("f118.load_failed");
  await act(async () =>
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [new File(["x"], "report.md")] },
    }),
  );
  expect(screen.getByRole("button", { name: "nextStep" })).toBeDisabled();
  expect(registers()).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "nextStep" })).toBeEnabled(),
  );
  expect(mocks.error).toHaveBeenCalledWith(failure);
});
it("retires strategy and staged files across an identity/tenant change", async () => {
  const view = mount();
  await drop();
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  await screen.findByRole("spinbutton", { name: "splitLength" });
  view.update({ ...scope, tenantId: 202 });
  expect(
    screen.queryByRole("spinbutton", { name: "splitLength" }),
  ).not.toBeInTheDocument();
  expect(screen.queryByText("report.md")).not.toBeInTheDocument();
  expect(registers()).toHaveLength(0);
});
it("keeps a failed preview explicit and disables final confirmation", async () => {
  mocks.get.mockImplementation(async (url: string) =>
    url.endsWith("/upload-settings")
      ? uploadSettings()
      : { ...preview(), status: "error" },
  );
  mount();
  await drop();
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  fireEvent.click(await screen.findByRole("button", { name: "nextStep" }));
  await screen.findByText("previewFailed");
  expect(screen.getByRole("button", { name: "nextStep" })).toBeDisabled();
  expect(registers()).toHaveLength(0);
});

it("reuses a completed inline preview when advancing to comparison", async () => {
  mount();
  await drop();
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  fireEvent.click(
    await screen.findByRole("button", { name: "previewResults" }),
  );
  await screen.findByText("original chunk");
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "nextStep" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "nextStep" }));
  await screen.findByText("original-preview");
  expect(previews()).toHaveLength(1);
});
