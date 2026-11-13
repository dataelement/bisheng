import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { SpaceSettingsEditor } from "@/pages/KnowledgePage/components/SpaceSettingsEditor";
import type { KnowledgeSpaceInfo } from "@/controllers/API/knowledgeSpace";
// CJK input samples for character-width validation, independent of UI copy.
const ideograph = String.fromCodePoint(0x4e00);
const mocks = vi.hoisted(() => ({
  get: vi.fn(),
  put: vi.fn(),
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
vi.mock("@/components/bs-comp/permission/PermissionDialog", () => ({
  PermissionDialog: () => <p>permission-editor</p>,
}));
vi.mock("@/components/bs-ui/alertDialog/useConfirm", () => ({
  bsConfirm: mocks.confirm,
}));
const scope = {
  identityKey: "user:7",
  tenantId: 101,
  managementTenantId: 101,
  view: "ordinary" as const,
};
let info: KnowledgeSpaceInfo;
const clients: QueryClient[] = [];
function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  clients.push(client);
  return render(
    <QueryClientProvider client={client}>
      <SpaceSettingsEditor scope={scope} spaceId={7} onSaved={vi.fn()} />
    </QueryClientProvider>,
  );
}
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
  mocks.get.mockImplementation(async () => info);
  mocks.put.mockResolvedValue(info);
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
  mocks.confirm.mock.calls[0][0].onOk();
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
  expect(screen.queryByText("managePermission")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "confirm" }));
  await waitFor(() => expect(mocks.put).toHaveBeenCalled());
  expect(mocks.put.mock.calls[0][1]).toEqual({
    name: "Space",
    description: "original",
    is_released: true,
  });
});
it("keeps failed saves visible and allows retry without resetting user input", async () => {
  const error = new Error("save failed");
  mocks.put.mockRejectedValueOnce(error).mockResolvedValue(info);
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
