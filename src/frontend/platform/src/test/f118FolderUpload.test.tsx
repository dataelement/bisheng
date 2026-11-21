import { uploadSettings } from "./uploadWizardFixtures";
import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { KnowledgeQueryScope } from "@/controllers/hooks/knowledge";
import { SpaceFileUploadPanel } from "@/pages/KnowledgePage/components/SpaceFileUploadPanel";
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: mocks,
  showApiError: mocks.error,
}));
vi.mock("@/contexts/locationContext", async () => ({
  locationContext: (await import("react")).createContext({
    appConfig: {
      enableEtl4lm: true,
      enableMediaUpload: false,
      uploadFileMaxSize: 50,
    },
  }),
}));
vi.mock("@/pages/KnowledgePage/components/FileUploadSplitStrategy", () => ({
  default: () => null,
}));
vi.mock("@/pages/KnowledgePage/components/KnowledgeTooltip", () => ({
  KnowledgeHint: () => null,
}));
const scope: KnowledgeQueryScope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary",
};
const clients: QueryClient[] = [];
const row = (id: number, path: string, status = 2) => ({
  id,
  file_name: `file-${id}.txt`,
  knowledge_id: 7,
  file_type: 1,
  file_level_path: path,
  status,
});
function file(path: string) {
  const value = new File(["x"], path.split("/").pop()!);
  Object.defineProperty(value, "webkitRelativePath", {
    value: path,
    configurable: true,
  });
  return value;
}
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  const view = (parentId: number | null) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SpaceFileUploadPanel scope={scope} spaceId={7} parentId={parentId} />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const result = render(view(9));
  return { ...result, move: (parent: number) => result.rerender(view(parent)) };
}
async function pick(files = [file("Root/a.txt"), file("Root/Sub/b.csv")]) {
  await act(async () =>
    fireEvent.change(screen.getByLabelText("f118.upload_folder"), {
      target: { files },
    }),
  );
  const direct = screen.queryByRole("button", { name: "uploadDirectly" });
  if (direct && !direct.hasAttribute("disabled")) fireEvent.click(direct);
}
async function proceed() {
  const direct = screen.queryByRole("button", { name: "uploadDirectly" });
  if (!direct) return;
  await waitFor(() => expect(direct).toBeEnabled());
  fireEvent.click(direct);
}
const stages = () =>
  mocks.post.mock.calls.filter(([url]) => url.endsWith("/uploads"));
const registers = () =>
  mocks.post.mock.calls.filter(([url]) => url.endsWith("/folders/upload"));
beforeEach(() => {
  vi.resetAllMocks();
  mocks.post.mockImplementation(async (url: string, body: FormData) =>
    url.endsWith("/folders/upload")
      ? [row(81, "/9/11"), row(82, "/9/11/12")]
      : { file_path: `tmp/${(body.get("file") as File).name}`, upload_id: "a".repeat(32), repeat: false },
  );
  mocks.get.mockImplementation(
    async (
      _url: string,
      options: { params: { file_ids: number[]; parent_id: number } },
    ) => _url.endsWith("/upload-settings") ? uploadSettings() : ({
      data: options.params.file_ids.map((id) =>
        row(id, `/9/${options.params.parent_id}`),
      ),
      has_more: false,
      next_cursor: null,
      page_size: 100,
    }),
  );
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});

it("anchors the picker menu to each mouse click and returns focus for keyboard use", async () => {
  mount();
  const user = userEvent.setup();
  const trigger = screen.getByRole("button", { name: "f118.upload_picker_trigger" });
  vi.spyOn(trigger, "getBoundingClientRect").mockReturnValue(new DOMRect(40, 72, 920, 192));

  for (const coords of [{ clientX: 240, clientY: 120 }, { clientX: 680, clientY: 200 }]) {
    await user.pointer({ keys: "[MouseLeft]", target: trigger, coords });
    const menu = await screen.findByRole("menu");
    const anchor = document.getElementById(menu.getAttribute("aria-labelledby")!);

    expect(anchor).toHaveAttribute("aria-hidden", "true");
    expect(anchor).toHaveStyle({ left: `${coords.clientX}px`, top: `${coords.clientY}px` });

    await user.keyboard("{Escape}");
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  }

  await user.keyboard("{Enter}");
  const menu = await screen.findByRole("menu");
  const keyboardAnchor = document.getElementById(menu.getAttribute("aria-labelledby")!);
  expect(keyboardAnchor).toHaveStyle({ left: "40px", top: "264px" });
});

it.each([
  ["f118.choose_files", "file"],
  ["f118.choose_folder", "folder"],
] as const)("opens only the native picker for %s", async (label, kind) => {
  mount();
  const user = userEvent.setup();
  const filePicker = document.querySelector('input[type="file"]:not([webkitdirectory])')!;
  const folderPicker = screen.getByLabelText("f118.upload_folder");
  const selectFiles = vi.fn();
  const selectFolder = vi.fn();
  filePicker.addEventListener("click", selectFiles);
  folderPicker.addEventListener("click", selectFolder);
  expect(folderPicker).toHaveAttribute("webkitdirectory");
  expect(screen.queryByRole("button", { name: "f118.upload_folder" })).not.toBeInTheDocument();

  const trigger = screen.getByRole("button", { name: "f118.upload_picker_trigger" });
  if (kind === "file") {
    await user.click(trigger);
  } else {
    trigger.focus();
    await user.keyboard("{Enter}");
  }
  const item = await screen.findByRole("menuitem", { name: label });

  expect(selectFiles).not.toHaveBeenCalled();
  expect(selectFolder).not.toHaveBeenCalled();
  await user.click(item);

  expect(selectFiles).toHaveBeenCalledTimes(kind === "file" ? 1 : 0);
  expect(selectFolder).toHaveBeenCalledTimes(kind === "folder" ? 1 : 0);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it.each(["file", "folder"])(
  "switches %s task actions from cancel to retry/remove and then staged removal",
  async (kind) => {
    let finishUpload!: (value: { file_path: string; upload_id: string; repeat: boolean }) => void;
    mocks.post.mockImplementation(() => new Promise((resolve) => {
      finishUpload = resolve;
    }));
    mount();
    const selected = kind === "folder" ? file("Root/a.txt") : file("report.txt");
    const input = kind === "folder"
      ? screen.getByLabelText("f118.upload_folder")
      : document.querySelector('input[type="file"]')!;
    await act(async () => fireEvent.change(input, { target: { files: [selected] } }));
    await waitFor(() => expect(stages()).toHaveLength(1));
    expect(screen.getByRole("button", { name: "cancel" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "retry" })).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    expect(stages()[0][2].signal.aborted).toBe(true);
    expect(screen.queryByRole("button", { name: "cancel" })).toBeNull();
    expect(screen.getByRole("button", { name: "retry" })).toBeVisible();
    expect(screen.getByRole("button", { name: "delete" })).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "retry" }));
    await waitFor(() => expect(stages()).toHaveLength(2));
    expect(screen.getByRole("button", { name: "cancel" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "delete" })).toBeNull();
    expect(screen.queryByRole("button", { name: "retry" })).toBeNull();

    await act(async () => finishUpload({ file_path: "tmp/a", upload_id: "a".repeat(32), repeat: false }));
    await screen.findByText("f118.upload_staged");
    expect(screen.queryByRole("button", { name: "cancel" })).toBeNull();
    expect(screen.queryByRole("button", { name: "retry" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "delete" }));
    expect(screen.queryByText(kind === "folder" ? "Root" : "report.txt")).toBeNull();
    expect(screen.getByText("f118.upload_tasks_empty")).toBeVisible();
    expect(registers()).toHaveLength(0);
  },
);

it("stages the complete tree before one original registration with exact relative paths", async () => {
  const append = vi.spyOn(FormData.prototype, "append");
  mount();
  await pick();
  await proceed();
  await waitFor(() => expect(registers()).toHaveLength(1));
  const uploadNames = append.mock.calls
    .filter(([field]) => field === "file")
    .map(([, , filename]) => filename);
  append.mockRestore();
  expect(uploadNames).toEqual(["a.txt", "b.csv"]);
  expect(stages()).toHaveLength(2);
  expect(registers()[0][1]).toMatchObject({
    parent_id: 9,
    items: [
      { file_path: "tmp/a.txt", relative_path: "Root/a.txt", size: 1 },
      { file_path: "tmp/b.csv", relative_path: "Root/Sub/b.csv", size: 1 },
    ],
  });
  expect(mocks.post.mock.calls.some(([url]) => url.endsWith("/files"))).toBe(
    false,
  );
});
it("tracks actual descendant parents rather than querying all file IDs at the drop root", async () => {
  mocks.post.mockImplementation(async (url: string, body: FormData) =>
    url.endsWith("/folders/upload")
      ? [row(81, "/9/11", 5), row(82, "/9/11/12", 5)]
      : { file_path: `tmp/${(body.get("file") as File).name}`, upload_id: "a".repeat(32), repeat: false },
  );
  mount();
  await pick();
  await proceed();
  await waitFor(() => expect(mocks.get.mock.calls.filter(([url]) => url.endsWith("/children"))).toHaveLength(2));
  expect(mocks.get.mock.calls.filter(([url]) => url.endsWith("/children")).map((call) => call[1].params)).toEqual([
    { parent_id: 11, file_ids: [81], page_size: 100 },
    { parent_id: 12, file_ids: [82], page_size: 100 },
  ]);
  expect(screen.getAllByText("completed")).toHaveLength(2);
});
it("keeps staged inputs and frozen paths across a later staging failure and retry", async () => {
  let uploads = 0;
  mocks.post.mockImplementation(async (url: string, body: FormData) => {
    if (url.endsWith("/folders/upload")) return [row(81, "/9/11")];
    if (++uploads === 2) throw new Error("second stage failed");
    return {
      file_path: `tmp/${(body.get("file") as File).name}`,
      upload_id: "a".repeat(32), repeat: false,
    };
  });
  mount();
  const selected = [file("Root/a.txt"), file("Root/Sub/b.csv")];
  await pick(selected);
  await screen.findByRole("button", { name: "retry" });
  expect(registers()).toHaveLength(0);
  Object.defineProperty(selected[0], "webkitRelativePath", {
    value: "changed/path.txt",
  });
  fireEvent.click(screen.getByRole("button", { name: "retry" }));
  await proceed();
  await waitFor(() => expect(registers()).toHaveLength(1));
  expect(stages()).toHaveLength(3);
  expect(registers()[0][1].items[0].relative_path).toBe("Root/a.txt");
});
it.each(["cancel", "parent"])(
  "retires late folder staging on %s without registering a partial tree",
  async (kind) => {
    let resolve!: (value: { file_path: string; upload_id?: string; repeat: boolean }) => void;
    let count = 0;
    mocks.post.mockImplementation(async () =>
      ++count === 1
        ? { file_path: "tmp/a", upload_id: "a".repeat(32), repeat: false }
        : new Promise((yes) => {
            resolve = yes;
          }),
    );
    const view = mount();
    await pick();
    await waitFor(() => expect(stages()).toHaveLength(2));
    const signal = stages()[1][2].signal as AbortSignal;
    if (kind === "cancel")
      fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    else view.move(10);
    expect(signal.aborted).toBe(true);
    await act(async () => resolve({ file_path: "tmp/late", upload_id: "a".repeat(32), repeat: false }));
    expect(registers()).toHaveLength(0);
  },
);
it("rejects the original raw count cap and does not upload hidden roots", async () => {
  mount();
  await pick([file(".git/secret.txt")]);
  expect(stages()).toHaveLength(0);
  await pick(Array.from({ length: 1001 }, (_, i) => file(`Root/${i}.txt`)));
  expect(stages()).toHaveLength(0);
});

it("keeps the directory tree when a folder is dragged onto the upload area", async () => {
  mount();
  const fileEntry = {
    isDirectory: false,
    fullPath: "/Root/Sub/a.txt",
    file: (onRead: (file: File) => void) => onRead(new File(["x"], "a.txt")),
  };
  const directoryEntry = (children: unknown[]) => ({
    isDirectory: true,
    createReader() {
      const batches = [children, []];
      return {
        readEntries: (onRead: (entries: unknown[]) => void) => onRead(batches.shift() ?? []),
      };
    },
  });
  const folder = directoryEntry([directoryEntry([fileEntry])]);
  await act(async () =>
    fireEvent.drop(screen.getByRole("button", { name: "f118.upload_picker_trigger" }), {
      dataTransfer: {
        types: ["Files"],
        items: [{ kind: "file", webkitGetAsEntry: () => folder }],
      },
    }),
  );
  await proceed();
  await waitFor(() => expect(registers()).toHaveLength(1));
  expect(registers()[0][1].items[0].relative_path).toBe("Root/Sub/a.txt");
});
