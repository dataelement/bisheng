import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import UserSelectedKnowledgePicker from "@/pages/BuildPage/flow/FlowChat/UserSelectedKnowledgePicker";

const getAuthorizedKnowledgeSpaceOptionsApiMock = vi.fn();
const getKnowledgeSpaceChildrenApiMock = vi.fn();
const getKnowledgeSpaceFolderStatsApiMock = vi.fn();

vi.mock("@/controllers/API/knowledgeSpace", () => ({
  getAuthorizedKnowledgeSpaceOptionsApi: (...args: any[]) => getAuthorizedKnowledgeSpaceOptionsApiMock(...args),
  getKnowledgeSpaceChildrenApi: (...args: any[]) => getKnowledgeSpaceChildrenApiMock(...args),
  getKnowledgeSpaceFolderStatsApi: (...args: any[]) => getKnowledgeSpaceFolderStatsApiMock(...args),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => ({
      documentKnowledgeBase: "文档知识库",
      knowledgeSpace: "知识空间",
      searchKnowledgeSpaceName: "搜索知识空间名称",
    }[key] || key),
  }),
}));

function latestSelection(onChange: ReturnType<typeof vi.fn>) {
  return [...onChange.mock.calls].reverse().find(([value]) => value)?.[0];
}

describe("UserSelectedKnowledgePicker", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getAuthorizedKnowledgeSpaceOptionsApiMock.mockResolvedValue({
      data: [
        { id: 12, name: "营销空间", space_level: "team" },
        { id: 13, name: "运营空间", space_level: "team" },
      ],
    });
    getKnowledgeSpaceChildrenApiMock.mockImplementation(({ space_id }) => {
      if (String(space_id) === "13") {
        return Promise.resolve({
          data: [{ id: 3001, name: "复盘.md", type: "file", file_type: 1, status: 2 }],
        });
      }
      return Promise.resolve({
        data: [
          { id: 2001, name: "案例", type: "folder", file_type: 0, visible_success_file_num: 2 },
          { id: 1001, name: "话术.md", type: "file", file_type: 1, status: 2 },
        ],
      });
    });
    getKnowledgeSpaceFolderStatsApiMock.mockResolvedValue([
      { folder_id: 2001, visible_success_file_num: 2 },
    ]);
  });

  it("selects a whole knowledge space into the runtime payload", async () => {
    const onChange = vi.fn();
    render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

    await screen.findByText("营销空间");
    expect(screen.queryByRole("tab", { name: "文档知识库" })).not.toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("checkbox")[0]);

    await waitFor(() => {
      expect(latestSelection(onChange)).toMatchObject({
        mode: "source",
        whole_source: {
          source_type: "space",
          source_id: 12,
          source_name: "营销空间",
        },
        items: [],
      });
    });
  });

  it("keeps file and folder scope inside one selected knowledge space", async () => {
    const onChange = vi.fn();
    render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

    expect(await screen.findByText("团队空间")).toBeTruthy();

    fireEvent.click(await screen.findByText("营销空间"));
    fireEvent.click(await screen.findByText("案例"));
    fireEvent.click(await screen.findByText("话术.md"));

    await waitFor(() => {
      expect(latestSelection(onChange)).toMatchObject({
        mode: "items",
        whole_source: null,
        items: [
          { source_type: "space", source_id: 12, ref_type: "folder", id: 2001, name: "案例" },
          { source_type: "space", source_id: 12, ref_type: "file", id: 1001, name: "话术.md" },
        ],
        effective_file_count: 3,
      });
    });
  });

  it("clears previous scope when selecting files from another knowledge space", async () => {
    const onChange = vi.fn();
    render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

    fireEvent.click(await screen.findByText("营销空间"));
    fireEvent.click(await screen.findByText("话术.md"));
    fireEvent.click(await screen.findByText("运营空间"));
    fireEvent.click(await screen.findByText("复盘.md"));

    await waitFor(() => {
      expect(latestSelection(onChange)).toMatchObject({
        mode: "items",
        whole_source: null,
        items: [
          { source_type: "space", source_id: 13, ref_type: "file", id: 3001, name: "复盘.md" },
        ],
        effective_file_count: 1,
      });
    });
  });

  it("shows an over-limit state when selected folder scope expands beyond 20 files", async () => {
    getKnowledgeSpaceFolderStatsApiMock.mockResolvedValue([
      { folder_id: 2001, visible_success_file_num: 21 },
    ]);
    const onChange = vi.fn();
    render(<UserSelectedKnowledgePicker value={null} onChange={onChange} />);

    fireEvent.click(await screen.findByText("营销空间"));
    fireEvent.click(await screen.findByText("案例"));

    await waitFor(() => {
      expect(latestSelection(onChange)).toMatchObject({
        mode: "items",
        items: [{ source_type: "space", source_id: 12, ref_type: "folder", id: 2001, name: "案例" }],
        effective_file_count: 21,
      });
    });
  });

  it("calls onConfirm when the confirm button is enabled", async () => {
    const onChange = vi.fn();
    const onConfirm = vi.fn();
    render(<UserSelectedKnowledgePicker value={null} onChange={onChange} showConfirm onConfirm={onConfirm} />);

    fireEvent.click(await screen.findByRole("button", { name: "确认" }));

    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
