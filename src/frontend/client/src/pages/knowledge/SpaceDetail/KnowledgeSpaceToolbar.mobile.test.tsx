import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { KnowledgeSpaceToolbar } from "./KnowledgeSpaceToolbar";

let mockHostHeader = false;
let mockHostBack = false;
jest.mock("~/hooks/useClientEnvironment", () => ({
  useClientEnvironment: () => ({
    channel: "web",
    capabilities: {
      hasHostChatHeader: mockHostHeader,
      hasHostBackButton: mockHostBack,
    },
  }),
}));
jest.mock("@bisheng/ui", () => jest.requireActual("../../../../../packages/ui/src/components/Dropdown/Dropdown"));
jest.mock("~/api/knowledge", () => ({
  SortType: { NAME: "name", TYPE: "type", UPDATE_TIME: "update_time" },
  SortDirection: { ASC: "asc", DESC: "desc" },
  SpaceRole: { MEMBER: "member" },
}));
jest.mock("~/utils", () => ({
  cn: (...values: unknown[]) => values.filter(Boolean).join(" "),
}));
jest.mock("bisheng-icons", () => ({
  Outlined: new Proxy({}, { get: () => () => null }),
  Filled: new Proxy({}, { get: () => () => null }),
  Colored: new Proxy({}, { get: () => () => null }),
}));
jest.mock("./CompoundSearchInput", () => ({ CompoundSearchInput: () => null }));
jest.mock("./FileListToolbar", () => ({ FileListToolbar: () => null }));
jest.mock("./KnowledgeSpaceHeader", () => ({ KnowledgeSpaceHeader: () => null }));

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{`${location.pathname}${location.search}`}</div>;
}

function renderToolbar(model: Record<string, unknown>, path = "/knowledge/space/1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <KnowledgeSpaceToolbar model={model as never} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

afterEach(() => {
  mockHostBack = false;
  window.BishengMobile = undefined;
});

it.each([false, true])(
  "keeps mobile knowledge actions usable with host header=%s",
  async (hostHeader) => {
    mockHostHeader = hostHeader;
    const model = {
      localize: (key: string) => key,
      isH5: true,
      searchMode: false,
      space: { id: "1", name: "Space", role: "creator" },
      currentPath: [],
      selectedFiles: new Set(),
      selectableFiles: [],
      canUploadFile: true,
      canCreateFolder: true,
      fileInputRef: { current: null },
      folderInputRef: { current: null },
      ensureSpaceActions: jest.fn(),
      onOpenSystemMenu: jest.fn(),
      onOpenSearch: jest.fn(),
      onToggleSpaceList: jest.fn(),
      triggerUpload: jest.fn(),
      onCreateFolder: jest.fn(),
      handleSort: jest.fn(),
    };
    renderToolbar(model);
    expect(screen.getByRole("button", { name: "Space" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Space" }));
    expect(model.onToggleSpaceList).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "com_knowledge.search" }));
    expect(model.onOpenSearch).toHaveBeenCalledTimes(1);
    const menu = screen.queryByRole("button", { name: "com_nav_open_sidebar" });
    const back = screen.queryByRole("button", { name: "com_ui_go_back" });
    if (hostHeader) {
      expect(menu).toBeNull();
      expect(back).toBeNull();
    } else {
      expect(back).toBeNull();
      expect(menu).toBeVisible();
      fireEvent.click(menu!);
      expect(model.onOpenSystemMenu).toHaveBeenCalledTimes(1);
    }
    const openMenu = (name: string) => {
      const trigger = screen.getByRole("button", { name });
      expect(trigger).toBeVisible();
      fireEvent.keyDown(trigger, { key: "ArrowDown" });
    };
    openMenu("com_knowledge.sort_field");
    fireEvent.click(await screen.findByRole("menuitem", { name: "com_knowledge.sort_by_name_label" }));
    expect(model.handleSort).toHaveBeenCalledWith("name");
    openMenu("com_knowledge.more");
    fireEvent.click(await screen.findByRole("menuitem", { name: "com_knowledge.upload_file" }));
    expect(model.triggerUpload).toHaveBeenCalledTimes(1);
    openMenu("com_knowledge.more");
    fireEvent.click(await screen.findByRole("menuitem", { name: "com_knowledge.new_folder" }));
    expect(model.onCreateFolder).toHaveBeenCalledTimes(1);
  },
);

it("closes the mobile host page from the space root", () => {
  mockHostHeader = true;
  mockHostBack = true;
  const postMessage = jest.fn();
  window.BishengMobile = { postMessage };
  const onNavigateFolder = jest.fn();
  renderToolbar({
    localize: (key: string) => key,
    isH5: true,
    searchMode: false,
    space: { id: "1", name: "Space", role: "creator" },
    currentPath: [],
    selectedFiles: new Set(),
    selectableFiles: [],
    onNavigateFolder,
  });
  fireEvent.click(screen.getByRole("button", { name: "com_ui_go_back" }));
  expect(postMessage).toHaveBeenCalledWith(JSON.stringify({ type: "close" }));
  expect(onNavigateFolder).not.toHaveBeenCalled();
  expect(screen.getByTestId("location")).toHaveTextContent("/knowledge/space/1");
});

it("returns to the knowledge list when the page is not hosted", () => {
  mockHostHeader = true;
  mockHostBack = true;
  renderToolbar(
    {
      localize: (key: string) => key,
      isH5: true,
      searchMode: false,
      space: { id: "1", name: "Space", role: "creator" },
      currentPath: [],
      selectedFiles: new Set(),
      selectableFiles: [],
      onNavigateFolder: jest.fn(),
    },
    "/knowledge/space/1?tab=created",
  );
  fireEvent.click(screen.getByRole("button", { name: "com_ui_go_back" }));
  expect(screen.getByTestId("location")).toHaveTextContent("/knowledge?tab=created");
});

it("walks up one folder before closing the host page", () => {
  mockHostHeader = true;
  mockHostBack = true;
  const postMessage = jest.fn();
  window.BishengMobile = { postMessage };
  const onNavigateFolder = jest.fn();
  renderToolbar({
    localize: (key: string) => key,
    isH5: true,
    searchMode: false,
    space: { id: "1", name: "Space", role: "creator" },
    currentPath: [
      { id: "parent", name: "Parent" },
      { id: "child", name: "Child" },
    ],
    selectedFiles: new Set(),
    selectableFiles: [],
    onNavigateFolder,
  });
  fireEvent.click(screen.getByRole("button", { name: "com_ui_go_back" }));
  expect(onNavigateFolder).toHaveBeenCalledWith("parent");
  expect(postMessage).not.toHaveBeenCalled();
});
