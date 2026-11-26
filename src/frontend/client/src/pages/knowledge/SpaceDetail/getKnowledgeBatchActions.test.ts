import { getKnowledgeBatchActions } from "./getKnowledgeBatchActions";
import type { GetKnowledgeBatchActionsOptions } from "./knowledgeSpaceTypes";

jest.mock("bisheng-icons", () => ({ Outlined: new Proxy({}, { get: () => () => null }) }));

it.each([true, false])("uses file edit eligibility for mobile batch similar documents (space edit=%s)", (canEditSpace) => {
  const handleProcessSimilar = jest.fn();
  const options: GetKnowledgeBatchActionsOptions = {
    selectedFiles: new Set(["11"]),
    isAdmin: false,
    canEditSpace,
    versionManagementEnabled: true,
    handleProcessSimilar,
    handleManagePermission: jest.fn(),
    hasFailedFiles: false,
    hasFoldersSelected: false,
    canBatchMove: false,
    canBatchDelete: false,
    canBatchDownload: false,
    canBatchTag: false,
    canBatchRetry: false,
    handleBatchDownload: jest.fn(),
    handleBatchTag: jest.fn(),
    handleBatchMove: jest.fn(),
    handleSingleDownload: jest.fn(),
    handleBatchDelete: jest.fn(),
    handleBatchRetry: jest.fn(),
    hasSimilarSelected: !canEditSpace,
    singleSelectedId: "11",
    canManageSinglePermission: false,
    localize: key => key,
  };
  const { batchActions } = getKnowledgeBatchActions(options);
  expect(batchActions.map(action => action.key)).toEqual(!canEditSpace ? ["similar"] : []);
  batchActions.find(action => action.key === "similar")?.onClick();
  expect(handleProcessSimilar).toHaveBeenCalledTimes(!canEditSpace ? 1 : 0);
});
