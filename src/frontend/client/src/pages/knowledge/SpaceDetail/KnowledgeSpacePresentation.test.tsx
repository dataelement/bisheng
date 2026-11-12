import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { KnowledgeSpacePresentation } from "./KnowledgeSpacePresentation";
import type { KnowledgeSpaceModel } from "./index";

jest.mock("~/hooks", () => ({ useLocalize: () => (key: string) => key }));
jest.mock("~/utils", () => ({ cn: (...values: unknown[]) => values.filter(Boolean).join(" ") }));
jest.mock("~/components/illustrations", () => ({ EmptyStateIllustration: () => null }));
jest.mock("~/components/ui/icon/Loading", () => ({ LoadingIcon: () => null }));
jest.mock("~/api/knowledge", () => ({ FileType: {}, SpaceRole: { MEMBER: "member" } }));
jest.mock("@bisheng/ui", () => ({
  Dropdown: ({ children }: { children: ReactNode }) => <>{children}</>,
  DropdownGroup: () => null, DropdownItem: () => null, DropdownSeparator: () => null,
}));
jest.mock("./KnowledgeSpaceHeader", () => ({ KnowledgeSpaceHeader: () => <button>Normal space actions</button> }));
jest.mock("./FileListToolbar", () => ({ FileListToolbar: () => <button>Normal file toolbar</button> }));
jest.mock("./FileCard", () => ({ FileCard: () => null }));
jest.mock("./FileListView", () => ({ FileListView: () => null }));
jest.mock("./SelectionPathBreadcrumb", () => ({ SelectionPathBreadcrumb: () => null }));
jest.mock("./KnowledgeSpaceOverlays", () => ({ KnowledgeSpaceOverlays: () => null }));
jest.mock("./KnowledgeDeletionDialog", () => ({ KnowledgeDeletionDialog: () => null }));
jest.mock("./BatchOperationDialog", () => ({ BatchOperationDialog: () => null }));

it.each([3, 4])("keeps the normal toolbar and state %s while removing all four standalone actions for a privileged viewer", (state) => {
  const model = {
    localize: (key: string) => key,
    space: { id: "3", role: "creator", name: "Space", state },
    isH5: false, currentPath: [], selectableFiles: [], selectedFiles: new Set(),
    displayFiles: [], contextMenuPosition: { x: 0, y: 0 },
    viewMode: "list", statusFilter: [],
    canEditSpace: true, canDeleteSpace: true, canBatchDelete: true,
    moveProgress: { available: true },
  } as unknown as KnowledgeSpaceModel;
  render(<KnowledgeSpacePresentation model={model} />);
  expect(screen.getByText("Normal space actions")).toBeVisible();
  expect(screen.getByText("Normal file toolbar")).toBeVisible();
  expect(screen.getByRole("status")).toBeVisible();
  for (const key of ["move_progress_title", "processing_jobs.title", "deletion.references", "deletion.clear"])
    expect(screen.queryByText(`com_knowledge.${key}`)).toBeNull();
});
