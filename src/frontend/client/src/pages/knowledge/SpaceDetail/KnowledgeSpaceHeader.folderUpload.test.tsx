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
jest.mock("../knowledgeUploadCapabilities", () => ({
  knowledgeUploadCapabilities: { webLink: false },
}));

const space = {
  id: "1",
  name: "Space",
  role: SpaceRole.CREATOR,
  visibility: VisibilityType.PRIVATE,
  creator: "Creator",
  creatorId: "7",
  memberCount: 1,
  fileCount: 0,
  totalFileCount: 0,
  isPinned: false,
  createdAt: "",
  updatedAt: "",
  tags: [],
  isReleased: false,
};

function renderHeader(canUploadFolder: boolean) {
  const onTriggerUploadFolder = jest.fn();
  render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <KnowledgeSpaceHeader
        space={space}
        currentPath={[]}
        onNavigateFolder={jest.fn()}
        isSearching={false}
        canCreateFolder={false}
        onCreateFolder={jest.fn()}
        onTriggerUpload={jest.fn()}
        onTriggerUploadFolder={onTriggerUploadFolder}
        onTriggerWebLink={jest.fn()}
        selectedCount={0}
        hasFoldersSelected={false}
        hasFailedFiles={false}
        onClearSelection={jest.fn()}
        onBatchDownload={jest.fn()}
        onBatchTag={jest.fn()}
        onBatchRetry={jest.fn()}
        onBatchDelete={jest.fn()}
        canUploadFile
        canUploadFolder={canUploadFolder}
      />
    </MemoryRouter>,
  );
  return onTriggerUploadFolder;
}

it("shows upload folder when canUploadFolder is true", async () => {
  const onTriggerUploadFolder = renderHeader(true);
  fireEvent.keyDown(screen.getByRole("button", { name: "com_knowledge.add_new" }), { key: "ArrowDown" });
  fireEvent.click(await screen.findByRole("menuitem", { name: "com_knowledge.upload_folder" }));
  expect(onTriggerUploadFolder).toHaveBeenCalledTimes(1);
});

it("hides upload folder when canUploadFolder is false", async () => {
  renderHeader(false);
  fireEvent.keyDown(screen.getByRole("button", { name: "com_knowledge.add_new" }), { key: "ArrowDown" });
  expect(await screen.findByRole("menuitem", { name: "com_knowledge.upload_file" })).toBeVisible();
  expect(screen.queryByRole("menuitem", { name: "com_knowledge.upload_folder" })).not.toBeInTheDocument();
});
