import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { SpaceRole, VisibilityType } from "~/api/knowledge";
import { KnowledgeSpaceHeader } from "./KnowledgeSpaceHeader";

jest.mock("~/api/knowledge", () => ({
  SpaceRole: { CREATOR: "creator", ADMIN: "admin", MEMBER: "member" },
  VisibilityType: { PRIVATE: "private" },
}));
jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("recoil", () => ({ useRecoilValue: () => undefined }));
jest.mock("~/pages/appChat/store/atoms", () => ({ bishengConfState: {} }));
jest.mock("~/components/CopyShareLinkButton", () => ({ CopyShareLinkButton: () => null }));
jest.mock("./SpaceBreadcrumb", () => ({ SpaceBreadcrumb: () => null }));
jest.mock("@bisheng/ui", () => jest.requireActual("../../../../../packages/ui/src/components/Dropdown/Dropdown"));
jest.mock("bisheng-icons", () => ({ Outlined: new Proxy({}, { get: () => () => null }) }));

it("shows the desktop batch menu as soon as a file is selected and hides it after clearing selection", async () => {
  const onBatchDownload = jest.fn();
  const space = {
    id: "1", name: "Space", role: SpaceRole.CREATOR, visibility: VisibilityType.PRIVATE,
    creator: "Creator", creatorId: "7", memberCount: 1, fileCount: 2, totalFileCount: 2,
    isPinned: false, createdAt: "", updatedAt: "", tags: [], isReleased: false,
  };
  const header = (selectedCount: number) => (
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <KnowledgeSpaceHeader
        space={space}
        currentPath={[]}
        onNavigateFolder={jest.fn()}
        isSearching={false}
        canCreateFolder
        onCreateFolder={jest.fn()}
        onTriggerUpload={jest.fn()}
        onTriggerUploadFolder={jest.fn()}
        onTriggerWebLink={jest.fn()}
        selectedCount={selectedCount}
        hasFoldersSelected={false}
        hasFailedFiles={false}
        onClearSelection={jest.fn()}
        canBatchDownload={selectedCount > 0}
        onBatchDownload={onBatchDownload}
        onBatchTag={jest.fn()}
        onBatchRetry={jest.fn()}
        onBatchDelete={jest.fn()}
      />
    </MemoryRouter>
  );
  const batchMenu = { name: "com_knowledge.batch_operation" };
  const { rerender } = render(header(0));
  expect(screen.queryByRole("button", batchMenu)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "com_knowledge.add_new" })).toBeVisible();

  rerender(header(1));
  const batchTrigger = screen.getByRole("button", batchMenu);
  expect(batchTrigger).toBeVisible();
  fireEvent.keyDown(batchTrigger, { key: "ArrowDown" });
  expect(await screen.findByRole("menuitem", { name: "com_knowledge.batch_download" })).toBeVisible();
  expect(screen.queryByRole("menuitem", { name: "com_knowledge.batch_add_tags" })).not.toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "com_knowledge.move" })).not.toBeInTheDocument();
  expect(screen.queryByRole("menuitem", { name: "com_knowledge.batch_delete" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("menuitem", { name: "com_knowledge.batch_download" }));
  expect(onBatchDownload).toHaveBeenCalledTimes(1);

  rerender(header(2));
  expect(screen.getByRole("button", batchMenu)).toBeVisible();

  rerender(header(0));
  expect(screen.queryByRole("button", batchMenu)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "com_knowledge.add_new" })).toBeVisible();
});

it.each([
  [true, false, true, true],
  [false, true, true, false],
  [true, true, false, false],
])("gates batch similar documents by edit (edit=%s, manage=%s, enabled=%s)", async (edit, manage, enabled, shown) => {
  const onProcessSimilar = jest.fn();
  render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <KnowledgeSpaceHeader
        space={{
          id: "1", name: "Space", role: SpaceRole.MEMBER, visibility: VisibilityType.PRIVATE,
          creator: "Creator", creatorId: "7", memberCount: 1, fileCount: 2, totalFileCount: 2,
          isPinned: false, createdAt: "", updatedAt: "", tags: [], isReleased: false,
        }}
        currentPath={[]}
        onNavigateFolder={jest.fn()}
        isSearching={false}
        onCreateFolder={jest.fn()}
        onTriggerUpload={jest.fn()}
        onTriggerUploadFolder={jest.fn()}
        onTriggerWebLink={jest.fn()}
        selectedCount={1}
        hasFoldersSelected={false}
        hasFailedFiles={false}
        onClearSelection={jest.fn()}
        onBatchDownload={jest.fn()}
        onBatchTag={jest.fn()}
        onBatchRetry={jest.fn()}
        onBatchDelete={jest.fn()}
        canEditSpace={edit}
        canManageMembers={manage}
        versionManagementEnabled={enabled}
        hasSimilarSelected
        onProcessSimilar={onProcessSimilar}
      />
    </MemoryRouter>,
  );
  const label = "com_knowledge.version.header_process_similar_label";
  if (shown) {
    fireEvent.keyDown(screen.getByRole("button", { name: "com_knowledge.batch_operation" }), { key: "ArrowDown" });
    fireEvent.click(await screen.findByRole("menuitem", { name: label }));
    expect(onProcessSimilar).toHaveBeenCalledTimes(1);
  } else {
    expect(screen.queryByRole("button", { name: "com_knowledge.batch_operation" })).not.toBeInTheDocument();
    expect(onProcessSimilar).not.toHaveBeenCalled();
  }
});
