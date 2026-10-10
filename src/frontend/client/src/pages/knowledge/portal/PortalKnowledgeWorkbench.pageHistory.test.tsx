import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RecoilRoot } from "recoil";
import { MemoryRouter } from "react-router-dom";
import PortalKnowledgeWorkbench from "./PortalKnowledgeWorkbench";
import { getSpaceChildrenApi, searchSpaceChildrenApi, getSpacesByLevelApi, getSpaceInfoApi, getCreateSpaceOptionsApi, getSpaceFolderStatsApi, getFolderParentPathApi, getFilePreviewApi } from "~/api/knowledge";
import store from "~/store";
import translations from "~/locales/zh-Hans/translation.json";

const mockToast = jest.fn();
const mockUpload = { creatingFolder: null, uploadingFiles: [], handleDeleteFile: jest.fn(), handleRenameFile: jest.fn() };
jest.mock("~/Providers", () => ({ useToastContext: () => ({ showToast: mockToast }), useConfirm: () => jest.fn() }));
jest.mock("~/hooks", () => ({
    useAuthContext: () => ({ user: { role: "user" } }), usePrefersMobileLayout: () => false,
    useLocalize: () => (key: string, values: Record<string, unknown> = {}) => {
        const words = jest.requireActual("~/locales/zh-Hans/translation.json").com_knowledge;
        return Object.entries(values).reduce((text, [name, value]) => text.replaceAll(`{{${name}}}`, String(value)), words[key.split(".")[1]] || key);
    },
}));
jest.mock("~/hooks/queries/endpoints/queries", () => ({ useGetBsConfig: () => ({ data: {} }), useGetPortalMetadataConfig: () => ({ data: {} }) }));
jest.mock("~/api/permission", () => ({ checkPermission: jest.fn(async () => ({ allowed: true })), canOpenPermissionDialog: jest.fn() }));
jest.mock("~/api/knowledge", () => ({
    ...jest.requireActual("~/api/knowledge"),
    getSpaceChildrenApi: jest.fn(), searchSpaceChildrenApi: jest.fn(), getSpacesByLevelApi: jest.fn(), getSpaceInfoApi: jest.fn(),
    getCreateSpaceOptionsApi: jest.fn(), getSpaceFileCountApi: jest.fn(), getSpaceFolderStatsApi: jest.fn(), getFolderParentPathApi: jest.fn(), getFilePreviewApi: jest.fn(),
}));
jest.mock("../hooks/useFileUpload", () => ({ useFileUpload: () => mockUpload }));
jest.mock("./hooks/usePortalUploadDialog", () => ({ usePortalUploadDialog: () => ({ uploadFolderNodes: [], uploadFiles: [], uploadReviewRows: [], fileCategoryGroups: [], businessDomainOptions: [] }) }));
jest.mock("../hooks/useKnowledgeSpacePermissions", () => ({
    useKnowledgeSpaceActionPermissions: () => ({ permissions: {} }), hasRoleBasedSpaceActionBypass: () => true,
    hasKnowledgeSpacePermission: () => true, isSystemAdmin: () => false,
}));
jest.mock("../hooks/useAiSplitPane", () => ({ useAiSplitPane: () => ({ showAiAssistant: false, splitContainerRef: { current: null }, setShowAiAssistant: jest.fn() }) }));
jest.mock("./components/PortalDialogs", () => ({ PortalDialogs: () => null }));
jest.mock("./components/PortalFileInfoEditModal", () => ({ PortalFileInfoEditModal: () => null }));
jest.mock("./components/PortalUploadedFilesDrawer", () => ({ PortalUploadedFilesDrawer: () => null }));
jest.mock("./components/PortalHeaderActions", () => ({ PortalHeaderActions: () => null }));
jest.mock("./components/PortalFavoritesPanel", () => () => null);
jest.mock("../SpaceDetail/AiChat/KnowledgeAiPanel", () => ({ KnowledgeAiPanel: () => null }));
jest.mock("./components/PortalPreviewWorkspace", () => ({ PortalPreviewWorkspace: ({ onBackToFileList, selectedFile }: any) => <div><span>预览：{selectedFile.name}</span><button onClick={onBackToFileList}>返回列表</button></div> }));
jest.mock("./components/SpaceSidebar", () => ({ SpaceSidebar: ({ groups, onSelectSpace }: any) => <aside>{groups.flatMap((group: any) => group.spaces).map((space: any) => <button key={space.id} onClick={() => onSelectSpace(space)}>{space.name}</button>)}</aside> }));
jest.mock("../SpaceDetail", () => ({
    KnowledgeSpaceContent: ({ files, paginationFooter, onNavigateFolder, onSearch, onPreviewFile, onDeleteFile, loading, listError }: any) => <section>
        <button onClick={() => onNavigateFolder()}>根目录</button>
        <button onClick={() => onDeleteFile(files[0]?.id)}>删除当前</button>
        <button onClick={() => onSearch({ keyword: "查找", tagIds: [], scope: "current" })}>搜索</button>
        <button onClick={() => onSearch({ keyword: "", tagIds: [], scope: "current" })}>清空搜索</button>
        {loading && <span>列表加载中</span>}{listError}
        {files.map((file: any) => <button key={file.id} onClick={() => file.type === "folder" ? onNavigateFolder(file.id, file.name) : onPreviewFile(file)}>{file.name}<span>{file.fileNum !== undefined ? `统计${file.fileNum}` : ""}</span></button>)}
        {paginationFooter}
    </section>,
}));

const space = (id: string) => ({ id, name: `知识库${id}`, role: "creator", spaceLevel: "personal", tags: [] });
const row = (id: string, name = `文档${id}`, extra = {}) => ({ id, name, type: "md", tags: [], spaceId: "1", status: "success", createdAt: "", updatedAt: "", ...extra });
const reply = (data: unknown[], next: string | null = null) => ({ data, has_more: Boolean(next), next_cursor: next, can_reorder_folders: false, page_size: 20 });
function openWorkbench() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, cacheTime: 0 } } });
    return render(<QueryClientProvider client={client}><MemoryRouter><RecoilRoot initializeState={({ set }) => set(store.user, { id: "user", role: "user" } as any)}><PortalKnowledgeWorkbench /></RecoilRoot></MemoryRouter></QueryClientProvider>);
}
const next = () => fireEvent.click(screen.getByRole("button", { name: "下一页" }));
beforeEach(() => {
    jest.clearAllMocks();
    jest.mocked(getSpacesByLevelApi).mockImplementation(async level => level === "personal" ? [space("1"), space("2")] as any : []);
    jest.mocked(getSpaceInfoApi).mockImplementation(async id => space(String(id)) as any);
    jest.mocked(getCreateSpaceOptionsApi).mockResolvedValue({ departments: [], userGroups: [] } as any);
    jest.mocked(getSpaceFolderStatsApi).mockResolvedValue([]);
    jest.mocked(getFolderParentPathApi).mockResolvedValue([]);
    jest.mocked(getFilePreviewApi).mockResolvedValue({ file_url: "/file", file_type: "md" } as any);
    jest.mocked(searchSpaceChildrenApi).mockImplementation(async params => ({ data: [row(`s${params.page}`)], total: 41, page: params.page, page_size: 20 }) as any);
    jest.mocked(getSpaceChildrenApi).mockImplementation(async ({ parent_id, cursor, space_id }) => {
        if (parent_id) return reply([row(cursor ? "f2" : "f1")], cursor ? null : "folder-2") as any;
        if (space_id === "2") return reply([row("other", "另一个库", { spaceId: "2" })]) as any;
        return cursor === "root-3" ? reply([row("3")]) as any
            : cursor ? reply([row("2")], "root-3") as any : reply([row("10", "目录", { type: "folder" }), row("1")], "root-2") as any;
    });
});

it("目录和根目录单页翻页、旧页零请求、跨库与预览恢复位置", async () => {
    openWorkbench();
    await screen.findByText("文档1");
    next(); await screen.findByText("文档2");
    expect(screen.queryByText("文档1")).toBeNull();
    const calls = jest.mocked(getSpaceChildrenApi).mock.calls.length;
    fireEvent.click(screen.getByRole("button", { name: "上一页" })); await screen.findByText("文档1");
    expect(getSpaceChildrenApi).toHaveBeenCalledTimes(calls);
    fireEvent.click(screen.getByText("目录")); await screen.findByText("文档f1");
    next(); await screen.findByText("文档f2");
    fireEvent.click(screen.getByText("文档f2")); await screen.findByText("预览：文档f2");
    fireEvent.click(screen.getByText("返回列表")); await screen.findByText("文档f2");
    expect(screen.getByText(/第 2 页，已浏览到第 2 页/)).toBeInTheDocument();
    fireEvent.click(screen.getByText("知识库2")); await screen.findByText("另一个库");
    fireEvent.click(screen.getByText("知识库1")); await screen.findByText("文档f2");
    expect(getSpaceChildrenApi).toHaveBeenCalledTimes(calls + 3);
});

it("搜索使用页码请求，清空搜索恢复目录历史", async () => {
    openWorkbench(); await screen.findByText("文档1"); next(); await screen.findByText("文档2");
    fireEvent.click(screen.getByText("搜索")); await screen.findByText("文档s1");
    next(); await screen.findByText("文档s2");
    expect(searchSpaceChildrenApi).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2, page_size: 20, keyword: "查找" }));
    fireEvent.click(screen.getByText("清空搜索")); await screen.findByText("文档2");
    expect(screen.getByText(/第 2 页，已浏览到第 2 页/)).toBeInTheDocument();
});

it("下一页失败保留原页，重试才推进；焦点只验证当前页", async () => {
    openWorkbench(); await screen.findByText("文档1");
    jest.mocked(getSpaceChildrenApi).mockRejectedValueOnce(new Error("offline"));
    next(); await waitFor(() => expect(mockToast).toHaveBeenCalled());
    expect(screen.getByText("文档1")).toBeInTheDocument();
    expect(screen.getByText("第 1 页，已浏览到第 1 页")).toBeInTheDocument();
    next(); await screen.findByText("文档2");
    jest.mocked(getSpaceChildrenApi).mockClear();
    await act(async () => window.dispatchEvent(new Event("focus")));
    await waitFor(() => expect(getSpaceChildrenApi).toHaveBeenCalledTimes(1));
    expect(getSpaceChildrenApi).toHaveBeenLastCalledWith(expect.objectContaining({ cursor: "root-2" }));
    expect(screen.getByText("文档2")).toBeInTheDocument();
});


it("结构更新和认证变化使旧页失效并只重取第一页", async () => {
    openWorkbench(); await screen.findByText("文档1"); next(); await screen.findByText("文档2");
    jest.mocked(getSpaceChildrenApi).mockClear();
    fireEvent.click(screen.getByText("删除当前")); await screen.findByText("文档1");
    expect(screen.getByText(/第 1 页，已浏览到第 1 页/)).toBeInTheDocument();
    expect(getSpaceChildrenApi).toHaveBeenCalledTimes(1);
    next(); await screen.findByText("文档2");
    jest.mocked(getSpaceChildrenApi).mockClear();
    await act(async () => window.dispatchEvent(new CustomEvent("tokenUpdated", { detail: "test-session" })));
    await screen.findByText("文档1");
    expect(getSpaceChildrenApi).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/第 1 页，已浏览到第 1 页/)).toBeInTheDocument();
});

it("搜索目录统计使用本次请求的关键词，避免沿用普通目录闭包", async () => {
    openWorkbench(); await screen.findByText("文档1");
    jest.mocked(searchSpaceChildrenApi).mockResolvedValueOnce({ data: [row("20", "搜索目录", { type: "folder" })], total: 1 } as any);
    fireEvent.click(screen.getByText("搜索")); await screen.findByText("搜索目录");
    await waitFor(() => expect(getSpaceFolderStatsApi).toHaveBeenCalledWith(expect.objectContaining({
        space_id: "1", folder_ids: ["20"], keyword: "查找",
    })));
});


it("认证更新后丢弃旧目录统计回包，即使知识库和文件 ID 相同", async () => {
    let resolveOld!: (value: any) => void;
    jest.mocked(getSpaceFolderStatsApi).mockReturnValueOnce(new Promise(resolve => { resolveOld = resolve; }));
    openWorkbench(); await screen.findByText("文档1");
    await waitFor(() => expect(getSpaceFolderStatsApi).toHaveBeenCalledTimes(1));
    await act(async () => window.dispatchEvent(new CustomEvent("tokenUpdated", { detail: "new-session" })));
    await waitFor(() => expect(getSpaceFolderStatsApi).toHaveBeenCalledTimes(2));
    await act(async () => resolveOld([{ folderId: "10", fileNum: 999, successFileNum: 999, visibleSuccessFileNum: 999, processingFileNum: 0 }]));
    expect(screen.queryByText("统计999")).toBeNull();
});

it("目录内搜索预览后返回原搜索页，深链接同步不覆盖浏览来源", async () => {
    jest.mocked(getFolderParentPathApi).mockImplementation(async (_space, fileId) => fileId === "10"
        ? [{ id: "10", name: "目录" }] : [{ id: "10", name: "目录" }, { id: "14", name: "子目录" }]);
    openWorkbench(); await screen.findByText("文档1");
    fireEvent.click(screen.getByText("目录")); await screen.findByText("文档f1");
    fireEvent.click(screen.getByText("搜索")); await screen.findByText("文档s1");
    next(); await screen.findByText("文档s2");
    fireEvent.click(screen.getByText("文档s2")); await screen.findByText("预览：文档s2");
    await waitFor(() => expect(getSpaceChildrenApi).toHaveBeenCalledWith(expect.objectContaining({ parent_id: "14" })));
    fireEvent.click(screen.getByText("返回列表")); await screen.findByText("文档s2");
    expect(screen.getByText(/第 2 页，已浏览到第 2 页/)).toBeInTheDocument();
    expect(screen.queryByText("文档f1")).toBeNull();
});
