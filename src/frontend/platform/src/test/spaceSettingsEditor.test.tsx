import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceSettingsEditor } from "@/pages/KnowledgePage/components/SpaceSettingsEditor";
import type {
  KnowledgeSpaceInfo,
  ProcessingSettingsRead,
  ProcessingSettingsWrite,
} from "@/controllers/API/knowledgeSpace";
// CJK input samples for character-width validation, independent of UI copy.
const ideograph = String.fromCodePoint(0x4e00);
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
  getProcessing: vi.fn(),
  putProcessing: vi.fn(),
  putBasic: vi.fn(),
  permission: vi.fn(),
  feature: vi.fn(),
  libraries: vi.fn(),
  library: vi.fn(),
  error: vi.fn(),
  confirm: vi.fn(),
}));
vi.mock("@/controllers/request", () => ({
  default: { get: mocks.get, put: mocks.put },
  showApiError: mocks.error,
}));
vi.mock("@/controllers/API/permission", () => ({
  getMyResourcePermissionsApi: mocks.permission,
}));
vi.mock("@/controllers/API/knowledgeSpaceTagLibrary", () => ({
  getKnowledgeSpaceAutoTagVisibilityApi: mocks.feature,
  getKnowledgeSpaceTagLibrariesApi: mocks.libraries,
  getKnowledgeSpaceTagLibraryApi: mocks.library,
}));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: mocks.confirm,
}));
vi.mock("@/pages/KnowledgePage/components/SpaceProcessingDialog", () => ({
  SpaceProcessingPanel: ({ jobKind }: { jobKind?: string }) => jobKind ? <div data-testid={`jobs-${jobKind}`} /> : null,
}));
const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
let info: KnowledgeSpaceInfo;
const settingsEndpoint = "/api/v1/knowledge/space/7";
const processingEndpoint = `${settingsEndpoint}/processing-settings`;
const processingSettings: ProcessingSettingsRead = {
  space_id: 7,
  config_version: 4,
  saved_defaults: null,
  effective_defaults: {
    schema_version: 1,
    document: {
      split_mode: "custom",
      separator: [""],
      separator_rule: ["after"],
      chunk_size: 300,
      chunk_overlap: 20,
      hierarchy_level: 3,
      append_title: false,
      max_chunk_size: 600,
      retain_images: 1,
      force_ocr: 1,
      enable_formula: 0,
      filter_page_header_footer: 1,
    },
    table: {
      slice_length: 10,
      header_start_row: 1,
      header_end_row: 2,
      append_header: 0,
    },
  },
};
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
    logger: { log: vi.fn(), warn: vi.fn(), error: vi.fn() },
  });
  clients.push(client);
  const saved = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <SpaceSettingsEditor scope={scope} spaceId={7} onSaved={saved} />
    </QueryClientProvider>,
  );
  return { ...view, saved };
}
const confirm = () => screen.getByRole("button", { name: "confirm" });
const readyForDefaults = () => screen.findByRole("spinbutton", { name: "splitLength" });
const enterText = (input: HTMLElement, value: string) =>
  fireEvent.change(input, { target: { value } });
beforeEach(() => {
  vi.resetAllMocks();
  info = {
    id: 7,
    name: "Space",
    description: "original",
    auth_type: "approval",
    is_released: true,
    auto_tag_enabled: false,
  };
  let currentProcessing = processingSettings;
  mocks.get.mockImplementation(async (path: string) =>
    path === processingEndpoint ? mocks.getProcessing() : info,
  );
  mocks.getProcessing.mockImplementation(async () => currentProcessing);
  mocks.put.mockImplementation(async (path: string, body: unknown) =>
    path === processingEndpoint ? mocks.putProcessing(body) : mocks.putBasic(body),
  );
  mocks.putBasic.mockImplementation(async (body: Partial<KnowledgeSpaceInfo>) => {
    info = { ...info, ...body };
    return info;
  });
  mocks.putProcessing.mockImplementation(async (body: ProcessingSettingsWrite) => {
    currentProcessing = {
      ...currentProcessing,
      config_version: body.expected_config_version + 1,
      saved_defaults: body.defaults,
      effective_defaults: body.defaults,
    };
    return currentProcessing;
  });
  mocks.permission.mockResolvedValue({
    actions: ["edit", "manage_permission"],
  });
  mocks.feature.mockResolvedValue({ visible: true });
  mocks.libraries.mockResolvedValue({
    data: [{ id: 8, name: "Library" }],
    total: 1,
  });
});
afterEach(() => {
  cleanup();
  clients.splice(0).forEach((client) => client.clear());
});
it("shows both index job histories in space settings", async () => {
  mount();
  expect(await screen.findByTestId("jobs-embedding_rebuild")).toBeVisible();
  expect(screen.getByTestId("jobs-move_index")).toBeVisible();
});
it("shows saved sharing options and saves custom automatic tags", async () => {
  mount();
  await screen.findByDisplayValue("Space");
  expect(
    screen.getByRole("switch", { name: "settings_ext.review" }),
  ).toBeChecked();
  expect(
    screen.getByRole("switch", { name: "settings_ext.publish" }),
  ).toBeChecked();
  fireEvent.click(
    screen.getByRole("switch", { name: "settings_ext.auto_tag" }),
  );
  fireEvent.mouseDown(
    await screen.findByRole("tab", { name: "settings_ext.custom" }),
    { button: 0, ctrlKey: false },
  );
  fireEvent.change(
    await screen.findByRole("textbox", { name: "settings_ext.custom_tags" }),
    { target: { value: "one\none\ntwo" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalled());
  expect(mocks.put.mock.calls[0]).toEqual([
    "/api/v1/knowledge/space/7",
    {
      name: "Space",
      description: "original",
      auth_type: "approval",
      is_released: true,
      auto_tag_enabled: true,
      auto_tag_library_id: null,
      auto_tag_custom_tags: ["one", "two"],
    },
  ]);
});
it("requires the existing private-space confirmation before changing access", async () => {
  mount();
  await screen.findByDisplayValue("Space");
  fireEvent.click(screen.getByRole("radio", { name: "settings_ext.private" }));
  expect(mocks.confirm).toHaveBeenCalled();
  expect(mocks.put).not.toHaveBeenCalled();
  act(() => mocks.confirm.mock.calls[0][0].onOk());
  await waitFor(() =>
    expect(
      screen.queryByRole("switch", { name: "settings_ext.review" }),
    ).toBeNull(),
  );
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalled());
  expect(mocks.put.mock.calls[0][1]).toMatchObject({
    auth_type: "private",
    is_released: false,
  });
});
it("prevents a department space from becoming private", async () => {
  info = { ...info, space_kind: "department", department_id: 22 };
  mount();
  await screen.findByDisplayValue("Space");
  expect(
    screen.getByRole("radio", { name: "settings_ext.private" }),
  ).toBeDisabled();
});
it("hides gated tag controls and preserves tags when saving basic information", async () => {
  mocks.feature.mockResolvedValue({ visible: false });
  info = { ...info, auto_tag_enabled: true, auto_tag_library_id: 8 };
  mount();
  await screen.findByDisplayValue("Space");
  expect(
    screen.queryByRole("switch", { name: "settings_ext.auto_tag" }),
  ).toBeNull();
  enterText(screen.getByDisplayValue("Space"), "changed");
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalled());
  expect(mocks.put.mock.calls[0][1]).not.toHaveProperty("auto_tag_enabled");
});
it("does not grant sharing management to a basic editor", async () => {
  mocks.permission.mockResolvedValue({ actions: ["edit"] });
  mount();
  await screen.findByDisplayValue("Space");
  expect(
    screen.getByRole("radio", { name: "settings_ext.private" }),
  ).toBeDisabled();
  enterText(screen.getByDisplayValue("Space"), "changed");
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalled());
  expect(mocks.put.mock.calls[0][1]).toEqual({
    name: "changed",
    description: "original",
    is_released: true,
  });
});
it("keeps failed saves visible and allows retry without resetting user input", async () => {
  const error = new Error("save failed");
  mocks.putBasic.mockRejectedValueOnce(error);
  mount();
  const name = await screen.findByDisplayValue("Space");
  fireEvent.change(name, { target: { value: "changed" } });
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  expect(screen.getByDisplayValue("changed")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalledTimes(2));
});
it("limits pasted names and descriptions using the client full-width rules", async () => {
  mount();
  const name = await screen.findByRole("textbox", { name: "f118.space_name" });
  fireEvent.change(name, { target: { value: "a".repeat(21) } });
  expect(name).toHaveValue("a".repeat(20));
  expect(screen.getByText("10/10")).toBeVisible();
  const description = screen.getByRole("textbox", {
    name: "f118.space_description",
  });
  fireEvent.change(description, { target: { value: "b".repeat(401) } });
  expect(description).toHaveValue("b".repeat(400));
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalled());
  expect(mocks.put.mock.calls[0][1]).toMatchObject({
    name: "a".repeat(20),
    description: "b".repeat(400),
  });
});
it("keeps IME composition intact and applies limits when composition finishes", async () => {
  mount();
  const name = await screen.findByRole("textbox", { name: "f118.space_name" });
  const value = ideograph.repeat(11);
  fireEvent.compositionStart(name);
  fireEvent.change(name, { target: { value } });
  expect(name).toHaveValue(value);
  expect(screen.getByRole("button", { name: "confirm" })).toBeDisabled();
  fireEvent.compositionEnd(name, { data: ideograph });
  expect(name).toHaveValue(ideograph.repeat(10));
  const description = screen.getByRole("textbox", {
    name: "f118.space_description",
  });
  fireEvent.compositionStart(description);
  fireEvent.change(description, { target: { value: ideograph.repeat(201) } });
  expect(description).toHaveValue(ideograph.repeat(201));
  fireEvent.compositionEnd(description, { data: ideograph });
  expect(description).toHaveValue(ideograph.repeat(200));
});

it("saves changed defaults before basic settings and uses the returned revision on the next save", async () => {
  const { saved } = mount();
  const length = await readyForDefaults();
  const name = await screen.findByDisplayValue("Space");
  expect(confirm()).toBeDisabled();
  enterText(name, "changed");
  enterText(length, "450");
  fireEvent.click(confirm());
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  expect(mocks.put.mock.calls).toEqual([
    [
      processingEndpoint,
      {
        expected_config_version: 4,
        defaults: {
          ...processingSettings.effective_defaults,
          document: {
            ...processingSettings.effective_defaults.document,
            chunk_size: 450,
          },
        },
      },
    ],
    [settingsEndpoint, expect.objectContaining({ name: "changed" })],
  ]);
  expect(confirm()).toBeDisabled();

  enterText(await readyForDefaults(), "500");
  fireEvent.click(confirm());
  await waitFor(() => expect(mocks.putProcessing).toHaveBeenCalledTimes(2));
  expect(mocks.putProcessing).toHaveBeenLastCalledWith(
    expect.objectContaining({ expected_config_version: 5 }),
  );
  expect(mocks.putBasic).toHaveBeenCalledTimes(1);
});

it("keeps both drafts and skips the basic write when the defaults revision is stale", async () => {
  const error = Object.assign(new Error("stale processing defaults"), { status_code: 18082 });
  mocks.putProcessing.mockRejectedValueOnce(error);
  mount();
  const name = await screen.findByDisplayValue("Space");
  const length = await readyForDefaults();
  enterText(name, "changed");
  enterText(length, "450");
  fireEvent.click(confirm());
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  expect(mocks.putBasic).not.toHaveBeenCalled();
  expect(name).toHaveValue("changed");
  expect(length).toHaveValue("450");
});

it("retries only the unfinished basic write after the defaults were saved", async () => {
  const error = new Error("basic settings save failed");
  mocks.putBasic.mockRejectedValueOnce(error);
  const { saved } = mount();
  const name = await screen.findByDisplayValue("Space");
  const length = await readyForDefaults();
  enterText(name, "changed");
  enterText(length, "450");
  fireEvent.click(confirm());
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith(error));
  expect(name).toHaveValue("changed");
  expect(length).toHaveValue("450");
  expect(screen.getByText("detail.processing_saved_settings_failed")).toBeVisible();

  fireEvent.click(confirm());
  await waitFor(() => expect(saved).toHaveBeenCalledTimes(1));
  expect(screen.queryByText("detail.processing_saved_settings_failed")).toBeNull();
  expect(mocks.put.mock.calls.map(([path]) => path)).toEqual([
    processingEndpoint,
    settingsEndpoint,
    settingsEndpoint,
  ]);
  expect(mocks.putBasic).toHaveBeenLastCalledWith(
    expect.objectContaining({ name: "changed" }),
  );
});

it("discards both drafts from the footer without writing either API", async () => {
  mount();
  const name = await screen.findByDisplayValue("Space");
  const length = await readyForDefaults();
  enterText(name, "changed");
  enterText(length, "450");
  fireEvent.click(screen.getByRole("button", { name: "cancel" }));
  expect(screen.getByDisplayValue("Space")).toBeVisible();
  expect(await readyForDefaults()).toHaveValue("300");
  expect(confirm()).toBeDisabled();
  expect(mocks.put).not.toHaveBeenCalled();
});

it("disables the unified save if either changed section is invalid", async () => {
  mount();
  const name = await screen.findByDisplayValue("Space");
  const length = await readyForDefaults();
  enterText(name, "changed");
  enterText(length, "");
  expect(confirm()).toBeDisabled();
  enterText(length, "450");
  expect(confirm()).toBeEnabled();
  enterText(name, "");
  expect(confirm()).toBeDisabled();
  expect(mocks.put).not.toHaveBeenCalled();
});

it.each(["loading", "failed"])("saves changed basic settings while untouched defaults are %s", async (status) => {
  if (status === "loading") {
    mocks.getProcessing.mockImplementation(() => new Promise(() => undefined));
  } else {
    mocks.getProcessing.mockRejectedValue(new Error("defaults failed to load"));
  }
  mount();
  const name = await screen.findByDisplayValue("Space");
  await waitFor(() => expect(mocks.getProcessing).toHaveBeenCalled());
  enterText(name, "changed");
  expect(confirm()).toBeEnabled();
  fireEvent.click(confirm());
  await waitFor(() => expect(mocks.putBasic).toHaveBeenCalledTimes(1));
  expect(mocks.putProcessing).not.toHaveBeenCalled();
});
