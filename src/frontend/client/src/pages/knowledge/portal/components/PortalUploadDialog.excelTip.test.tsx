/**
 * PortalUploadDialog：选择文件区域文案与提示。
 */
import { createRef } from "react";
import { render, screen } from "@testing-library/react";

import { PortalUploadDialog } from "./PortalUploadDialog";

function renderSelectStepDialog() {
  const noop = () => undefined;
  return render(
    <PortalUploadDialog
      open
      step="select"
      activeSpaceName="测试库"
      uploadInputRef={createRef<HTMLInputElement>()}
      uploadFolderInputRef={createRef<HTMLInputElement>()}
      uploadFiles={[]}
      uploadLocalFolderName={null}
      uploadFolderId={null}
      uploadFolderName=""
      uploadFolderSelection={{ mode: "ai" }}
      uploadFolderNodes={[]}
      uploadFolderLoading={false}
      uploadSubmitting={false}
      uploadImporting={false}
      uploadReviewRows={[]}
      uploadFolderOptions={[]}
      fileSubcategoryCode=""
      fileCategoryGroups={[]}
      businessDomainCode=""
      businessDomainOptions={[]}
      uploadTagOptions={[]}
      selectedUploadTagValues={[]}
      uploadTagLoading={false}
      fileInputAccept=".pdf,.xlsx"
      supportedFormatsLabel="pdf、xlsx"
      maxFileSizeMB={50}
      onOpen={noop}
      onClose={noop}
      onAddUploadFiles={noop}
      onAddUploadFolder={noop}
      onRemoveUploadFile={noop}
      onSelectFileCategory={noop}
      onSelectBusinessDomain={noop}
      onToggleUploadTag={noop}
      onClearUploadTags={noop}
      onSelectUploadFolder={noop}
      onUseAiUploadFolder={noop}
      onToggleUploadFolder={noop}
      onUploadNext={noop}
      onReviewRowsChange={noop}
      onBackToSelect={noop}
      onStartUploadImport={noop}
    />,
  );
}

describe("PortalUploadDialog excel tip", () => {
  it("选择文件区域展示 Excel 取消合并单元格提示", () => {
    renderSelectStepDialog();
    const dialog = screen.getByTestId("portal-upload-dialog");
    expect(dialog).toHaveTextContent("点击选择文件或拖拽文件到此处");
    expect(screen.getByTestId("upload-excel-merge-tip")).toHaveTextContent(
      "对于excel文档建议取消合并单元格",
    );
  });
});
