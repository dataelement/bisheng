import { fireEvent, render, screen } from "@testing-library/react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import request from "~/api/request";
import { getFileDownloadApi, getFilePreviewApi } from "~/api/knowledge";
import mockZhHans from "~/locales/zh-Hans/translation.json";
import { TopBar } from "./TopBar";

jest.mock("~/api/request", () => ({
  __esModule: true,
  default: {
    get: jest.fn(),
  },
}));
jest.mock("~/hooks/useLocalize", () => ({
  __esModule: true,
  default: () => (key: string) =>
    key === "com_knowledge.download_file" ? mockZhHans.com_knowledge.download_file : key,
}));

const mockedRequest = request as jest.Mocked<typeof request>;

describe("F048 file preview and download boundary", () => {
  beforeEach(() => {
    window.matchMedia = jest.fn().mockReturnValue({
      matches: false,
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    });
    mockedRequest.get.mockResolvedValue({
      status_code: 200,
      data: {
        original_url: "/original.pdf",
        preview_url: "/preview.pdf",
      },
    });
  });

  it("renders preview controls without performing an action check", () => {
    const onDownload = jest.fn();
    render(
      <TopBar
        fileName="Policy.pdf"
        showZoom={false}
        onDownload={onDownload}
      />,
    );

    expect(mockedRequest.get).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: mockZhHans.com_knowledge.download_file }),
    );
    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it("keeps preview and protected download endpoints separate", async () => {
    await getFilePreviewApi("space-1", "file-1");
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      1,
      "/api/v1/knowledge/space/space-1/files/file-1/preview",
    );

    await getFileDownloadApi("space-1", "file-1");
    expect(mockedRequest.get).toHaveBeenNthCalledWith(
      2,
      "/api/v1/knowledge/space/space-1/files/file-1/download",
    );
  });

  it("keeps route preview free of permission checks and permission management", () => {
    const source = readFileSync(
      resolve(
        process.cwd(),
        "src/pages/knowledge/FilePreview/FilePreviewPage.tsx",
      ),
      "utf8",
    );

    expect(source).not.toMatch(
      /checkPermission|checkResourceAction|getMyResourcePermissions|getResourcePermissionContext|PermissionDialog|can_read|permission_id|setCanDownload/,
    );
    expect(source).toContain("getFilePreviewApi(spaceId, fileId)");
    expect(source).toContain("getFileDownloadApi(spaceId, fileId)");
  });
});
