import { act, fireEvent, render, screen } from "@testing-library/react";
import { KnowledgeSpaceContent } from "./index";
import type { KnowledgeSpaceModel } from "./index";
import type { KnowledgeSpaceContentProps } from "./knowledgeSpaceTypes";

let mockNarrow = true;
const mockNoop = () => undefined;
const mockQueryClient = { invalidateQueries: jest.fn() };
const mockPermissions = jest.fn(async () => ({ actions: ["upload_file"] }));
jest.mock("recoil", () => ({
  useRecoilState: () => jest.requireActual("react").useState(new Set<string>()),
  useRecoilValue: () => ({}),
}));
jest.mock("../selectionStore", () => ({ knowledgeSelectedFilesState: {} }));
jest.mock("~/pages/appChat/store/atoms", () => ({ bishengConfState: {} }));
jest.mock("~/hooks", () => ({
  useLocalize: () => (key: string) => key,
  usePrefersMobileLayout: () => mockNarrow,
  useScrollRevealRef: () => mockNoop,
  useVersionManagementEnabled: () => false,
}));
jest.mock("~/Providers", () => ({
  useToastContext: () => ({ showToast: mockNoop }),
  useConfirm: () => mockNoop,
}));
jest.mock("@tanstack/react-query", () => ({
  useQueryClient: () => mockQueryClient,
}));
jest.mock("~/api/permission", () => ({
  getMyResourcePermissions: () => mockPermissions(),
}));
jest.mock("~/api/knowledge", () => ({
  FileStatus: { SUCCESS: "success" },
  FileType: { FOLDER: "folder" },
  SpaceRole: { CREATOR: "creator", ADMIN: "admin" },
  VisibilityType: { PRIVATE: "private" },
}));
jest.mock("~/hooks/useEffectiveQuota", () => ({
  useRefreshEffectiveQuota: () => mockNoop,
}));
jest.mock("~/hooks/usePersonalStorageQuota", () => ({
  useStorageQuotaGuard: () => mockNoop,
}));
jest.mock("../hooks/useKnowledgeSpacePermissions", () => ({
  useKnowledgeSpaceActions: () => ({
    actions: {},
    ensureSpaceActions: mockNoop,
  }),
  hasKnowledgeSpaceAction: () => false,
}));
jest.mock("../knowledgeUtils", () => ({
  getAllowedExtensions: () => [],
  getFileInputAccept: () => "",
  resolveUploadSizeLimits: () => ({ defaultMaxMB: 200 }),
  isKnowledgeItemRetryable: () => false,
  isKnowledgeItemUploading: () => false,
}));
jest.mock("../hooks/useFileDragDrop", () => ({ useFileDragDrop: () => ({}) }));
jest.mock("../hooks/useKnowledgeMoveDrag", () => ({
  useKnowledgeMoveDrag: () => ({}),
}));
jest.mock("../hooks/useKnowledgeMove", () => ({
  useKnowledgeMove: () => ({}),
}));
jest.mock("../hooks/useFileManager", () => ({
  dispatchKnowledgeSpaceFilesRefresh: () => mockNoop(),
}));
jest.mock("~/components/CopyShareLinkButton", () => ({
  buildClientShareUrl: (value: string) => value,
}));
jest.mock("~/utils", () => ({
  getFullWidthLength: (value: string) => value.length,
}));
jest.mock("./LoadMore", () => ({ LoadMore: () => null }));
jest.mock("./KnowledgeSpacePresentation", () => ({
  KnowledgeSpacePresentation: ({ model }: { model: KnowledgeSpaceModel }) => (
    <div>
      <input
        aria-label="Search"
        value={model.searchQuery}
        onChange={(event) =>
          model.handleSearch({
            keyword: event.target.value,
            tagIds: [],
            scope: "current",
          })
        }
      />
      <button onClick={() => model.handleSelectFile("1", true)}>
        Select file
      </button>
      <output>
        {model.selectedFiles.size}:{model.isH5 ? "narrow" : "wide"}
      </output>
    </div>
  ),
}));

it("preserves search and selection through narrow/wide layout without rechecking grants", async () => {
  const props: KnowledgeSpaceContentProps = {
    space: { id: "10", name: "Space" } as never,
    files: [{ id: "1", name: "File", type: "file" }] as never,
    total: 1,
    hasMore: false,
    loading: false,
    currentPath: [],
    onLoadMore: mockNoop,
    onSearch: mockNoop,
    onFilterStatus: mockNoop,
    onSort: mockNoop,
    onNavigateFolder: mockNoop,
    onUploadFile: mockNoop,
    onUploadFolder: mockNoop,
    onCreateFolder: mockNoop,
    onDownloadFile: mockNoop,
    onRenameFile: mockNoop,
    onDeleteFile: mockNoop,
    onBatchDeleteFiles: async () => true,
    onEditTags: mockNoop,
    onRetryFile: mockNoop,
  };
  const view = render(<KnowledgeSpaceContent {...props} />);
  await act(async () => {});
  fireEvent.change(screen.getByRole("textbox"), {
    target: { value: "Keep search" },
  });
  fireEvent.click(screen.getByText("Select file"));
  expect(screen.getByText("1:narrow")).toBeInTheDocument();
  const checks = mockPermissions.mock.calls.length;
  mockNarrow = false;
  view.rerender(<KnowledgeSpaceContent {...props} />);
  expect(screen.getByRole("textbox")).toHaveValue("Keep search");
  expect(screen.getByText("1:wide")).toBeInTheDocument();
  mockNarrow = true;
  view.rerender(<KnowledgeSpaceContent {...props} />);
  expect(screen.getByText("1:narrow")).toBeInTheDocument();
  expect(mockPermissions).toHaveBeenCalledTimes(checks);
});
