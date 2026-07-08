# 移动到弹窗支持文件夹重命名 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在知识库"移动到"弹窗（`MoveFolderDialog`）内，为已有文件夹增加悬停铅笔触发的内联重命名。

**Architecture:** 纯前端、单文件改动。复用现有 `renameFolderApi` 与现有内联"新建文件夹"的编辑范式，新增独立的 `renamingId`/`renamingName` 状态（方案 A），与新建态互斥。重命名成功后复用现有刷新链路（`dispatchKnowledgeSpaceFilesRefresh` + `onFolderCreated`）同步 SpaceDetail 左树/列表与 Portal 宿主列表。

**Tech Stack:** React + TypeScript，lucide-react 图标，Tailwind class，Jest + @testing-library/react + userEvent。

**对应设计文档：** `docs/superpowers/specs/2026-07-08-move-dialog-folder-rename-design.md`

## Global Constraints

- 只改一个源文件：`src/frontend/client/src/pages/knowledge/SpaceDetail/MoveFolderDialog.tsx`，外加新增一个同目录测试文件。不改后端、不改其他组件。
- 复用现有 API：`renameFolderApi(space_id: string, folder_id: string, name: string): Promise<void>`（`~/api/knowledge`）。
- 复用现有多语言 key：`com_knowledge.rename`（tooltip）；不新增任何 locale key。
- 复用现有刷新链路：`dispatchKnowledgeSpaceFilesRefresh(spaceId)` + `onFolderCreated?.()`。
- 同一时刻只允许一个内联编辑（新建 or 重命名），二者互斥。
- 遵循现有内联输入样式（蓝框 `border-[#165dff]`、`autoFocus`、聚焦全选、Enter/blur 提交、Escape 取消）。
- 所有涉及冒泡的按钮/输入需 `stopPropagation`，避免误触"选为移动目标"。
- 目录内测试文件命名遵循既有惯例 `*.rename.test.tsx`。

**工作目录：** 所有命令在 `src/frontend/client` 下执行（该目录是前端 client 包根，含 `package.json` 与 jest 配置）。

---

### Task 1: MoveFolderDialog 内联文件夹重命名

**Files:**
- Modify: `src/frontend/client/src/pages/knowledge/SpaceDetail/MoveFolderDialog.tsx`
- Test: `src/frontend/client/src/pages/knowledge/SpaceDetail/MoveFolderDialog.rename.test.tsx` (create)

**Interfaces:**
- Consumes:
  - `renameFolderApi(space_id: string, folder_id: string, name: string): Promise<void>` — from `~/api/knowledge`
  - `getSpaceChildrenApi(params): Promise<{ data: KnowledgeFile[]; page_size: number; has_more: boolean; next_cursor: string | null }>` — from `~/api/knowledge`
  - `FileType.FOLDER === "folder"` — from `~/api/knowledge`
  - `dispatchKnowledgeSpaceFilesRefresh(spaceId?: number | string): void` — from `../hooks/useFileManager`
  - `localize("com_knowledge.rename")` — 现有多语言 key
- Produces: 无对外新导出；`MoveFolderDialog` 的 props 契约不变。

- [ ] **Step 1: 写失败测试**

创建 `src/frontend/client/src/pages/knowledge/SpaceDetail/MoveFolderDialog.rename.test.tsx`：

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MoveFolderDialog } from "./MoveFolderDialog";
import {
    getSpaceChildrenApi,
    renameFolderApi,
    FileType,
} from "~/api/knowledge";
import { dispatchKnowledgeSpaceFilesRefresh } from "../hooks/useFileManager";

jest.mock("~/hooks", () => ({
    useLocalize: () => (key: string) => key,
}));

jest.mock("../hooks/useFileManager", () => ({
    dispatchKnowledgeSpaceFilesRefresh: jest.fn(),
}));

jest.mock("~/api/knowledge", () => {
    const actual = jest.requireActual("~/api/knowledge") as typeof import("~/api/knowledge");
    return {
        ...actual,
        getSpaceChildrenApi: jest.fn(),
        createFolderApi: jest.fn(),
        renameFolderApi: jest.fn(),
    };
});

const makeFolder = (id: string, name: string) =>
    ({ id, name, type: FileType.FOLDER } as any);

function mockChildren(list: any[]) {
    jest.mocked(getSpaceChildrenApi).mockResolvedValue({
        data: list,
        page_size: 200,
        has_more: false,
        next_cursor: null,
    } as any);
}

function renderDialog(overrides: Partial<Parameters<typeof MoveFolderDialog>[0]> = {}) {
    const props = {
        open: true,
        spaceId: "100",
        movingItemId: "999",
        movingItemType: "file" as const,
        onConfirm: jest.fn(),
        onCancel: jest.fn(),
        onFolderCreated: jest.fn(),
        ...overrides,
    };
    render(<MoveFolderDialog {...props} />);
    return props;
}

describe("MoveFolderDialog inline folder rename", () => {
    beforeEach(() => {
        jest.clearAllMocks();
        mockChildren([makeFolder("1", "旧名字")]);
        jest.mocked(renameFolderApi).mockResolvedValue(undefined as any);
    });

    it("点铅笔进入内联编辑，初值为当前名且被选中", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input = screen.getByDisplayValue("旧名字") as HTMLInputElement;
        expect(input).toBeInTheDocument();
        // autoFocus + onFocus 全选
        expect(input).toHaveFocus();
    });

    it("改名回车 → 以正确参数调用 renameFolderApi 并触发刷新与重拉", async () => {
        const props = renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input = screen.getByDisplayValue("旧名字");
        await userEvent.clear(input);
        await userEvent.type(input, "新名字{Enter}");

        await waitFor(() => {
            expect(renameFolderApi).toHaveBeenCalledWith("100", "1", "新名字");
        });
        expect(dispatchKnowledgeSpaceFilesRefresh).toHaveBeenCalledWith("100");
        expect(props.onFolderCreated).toHaveBeenCalled();
        // 初次加载 + 重命名后重拉
        expect(jest.mocked(getSpaceChildrenApi).mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    it("空名或与原名相同 → 不调用接口，收起编辑态", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();

        // 未修改直接回车
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        await userEvent.type(screen.getByDisplayValue("旧名字"), "{Enter}");
        expect(renameFolderApi).not.toHaveBeenCalled();

        // 清空后回车
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input2 = screen.getByDisplayValue("旧名字");
        await userEvent.clear(input2);
        await userEvent.type(input2, "{Enter}");
        expect(renameFolderApi).not.toHaveBeenCalled();
    });

    it("Escape 取消编辑并恢复原名", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const input = screen.getByDisplayValue("旧名字");
        await userEvent.clear(input);
        await userEvent.type(input, "改一半{Escape}");
        expect(renameFolderApi).not.toHaveBeenCalled();
        expect(screen.getByText("旧名字")).toBeInTheDocument();
        expect(screen.queryByDisplayValue("改一半")).not.toBeInTheDocument();
    });

    it("点铅笔不会把该行选为移动目标（确认按钮仍禁用）", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        const confirmBtn = screen.getByRole("button", { name: "com_bschoose_confirm" });
        expect(confirmBtn).toBeDisabled();
    });

    it("重命名与新建互斥：开始新建会关闭重命名", async () => {
        renderDialog();
        expect(await screen.findByText("旧名字")).toBeInTheDocument();
        await userEvent.click(screen.getByTitle("com_knowledge.rename"));
        expect(screen.getByDisplayValue("旧名字")).toBeInTheDocument();

        await userEvent.click(screen.getByText("com_knowledge.new_folder"));
        expect(screen.queryByDisplayValue("旧名字")).not.toBeInTheDocument();
        // 未改名的重命名被 blur 提交但因名字未变而跳过接口
        expect(renameFolderApi).not.toHaveBeenCalled();
        // 同一时刻只有一个内联输入（此时是新建输入框）
        expect(screen.getAllByRole("textbox")).toHaveLength(1);
    });
});
```

- [ ] **Step 2: 运行测试，确认失败**

Run: `npx jest src/pages/knowledge/SpaceDetail/MoveFolderDialog.rename.test.tsx`
Expected: FAIL —— 目前没有 `title="com_knowledge.rename"` 的铅笔按钮，`screen.getByTitle("com_knowledge.rename")` 找不到元素，多个用例报错。

- [ ] **Step 3a: 引入 Pencil 图标**

在 `MoveFolderDialog.tsx` 顶部，把 lucide-react 的 import 加上 `Pencil`：

替换：
```tsx
import { ChevronRight, Folder, FolderPlus, Home, Loader2 } from "lucide-react";
```
为：
```tsx
import { ChevronRight, Folder, FolderPlus, Home, Loader2, Pencil } from "lucide-react";
```

并确认已从 `~/api/knowledge` 导入 `renameFolderApi`（现有 import 行是 `getSpaceChildrenApi, createFolderApi, KnowledgeFile, FileType`），改为：
```tsx
import { getSpaceChildrenApi, createFolderApi, renameFolderApi, KnowledgeFile, FileType } from "~/api/knowledge";
```

- [ ] **Step 3b: 新增重命名状态**

在现有 `const submittingRef = useRef(false);` 之后新增：

```tsx
    // Inline rename: null = not renaming; string = the folder id being renamed
    const [renamingId, setRenamingId] = useState<string | null>(null);
    const [renamingName, setRenamingName] = useState("");
    // Guards against double-submit when Enter and blur both fire (rename)
    const renameSubmittingRef = useRef(false);
```

- [ ] **Step 3c: 打开弹窗 / 导航时重置重命名态**

在 `open` 的 `useEffect` 重置块内（现有 `setCreatingName(null);` 之后）加：
```tsx
            setRenamingId(null);
```

在 `handleNavigateInto` 内（现有 `setCreatingName(null);` 之后）加：
```tsx
        setRenamingId(null);
```

在 `handleBreadcrumbClick` 内（现有 `setCreatingName(null);` 之后）加：
```tsx
        setRenamingId(null);
```

在 `handleStartCreate` 内（现有 `setSelected(undefined);` 之后、设置 `creatingName` 之前或之后）加，保证开始新建时关闭重命名：
```tsx
        setRenamingId(null);
```

- [ ] **Step 3d: 新增重命名处理函数**

在 `handleConfirmCreate` 之后新增三个函数：

```tsx
    const handleStartRename = (folder: KnowledgeFile) => {
        // Mutual exclusion with the new-folder editor
        setCreatingName(null);
        setRenamingId(folder.id);
        setRenamingName(folder.name || "");
    };

    const handleCancelRename = () => setRenamingId(null);

    const handleConfirmRename = async (folder: KnowledgeFile) => {
        if (renameSubmittingRef.current || renamingId !== folder.id) return;
        const name = renamingName.trim();
        // No-op when empty or unchanged
        if (!name || name === (folder.name || "")) { setRenamingId(null); return; }
        renameSubmittingRef.current = true;
        setSavingFolder(true);
        try {
            await renameFolderApi(spaceId, folder.id, name);
            setRenamingId(null);
            await loadFolders(currentFolderId);
            // SpaceDetail: refresh its file list + left folder tree via the global event.
            dispatchKnowledgeSpaceFilesRefresh(spaceId);
            // Portal (and any host that manages its own list): refresh through the callback.
            onFolderCreated?.();
        } catch {
            // Error is surfaced by the response interceptor; keep the row for retry/cancel.
        } finally {
            renameSubmittingRef.current = false;
            setSavingFolder(false);
        }
    };
```

- [ ] **Step 3e: 改造文件夹行渲染**

把现有 `folders.map((folder) => ( ... ))` 整块替换为下面版本（新增：重命名态 input、铅笔按钮；重命名态下整行不再"点击选为目标"）：

```tsx
                        folders.map((folder) => {
                            const isRenaming = renamingId === folder.id;
                            return (
                                <div
                                    key={folder.id}
                                    onClick={() => { if (!isRenaming) setSelected(folder.id); }}
                                    className={cn(
                                        "flex items-center gap-2 px-3 py-2.5 border-b border-[#e5e6eb] last:border-b-0 text-sm transition-colors group",
                                        isRenaming
                                            ? "bg-[#f5f6fa]"
                                            : selected === folder.id
                                                ? "cursor-pointer bg-[#e8f3ff] text-[#165dff]"
                                                : "cursor-pointer hover:bg-[#f5f6fa] text-[#1d2129]"
                                    )}
                                >
                                    <Folder className="size-4 shrink-0 text-[#f7ba1e]" />
                                    {isRenaming ? (
                                        <>
                                            <input
                                                autoFocus
                                                value={renamingName}
                                                disabled={savingFolder}
                                                onChange={(e) => setRenamingName(e.target.value)}
                                                onFocus={(e) => e.target.select()}
                                                onClick={(e) => e.stopPropagation()}
                                                onKeyDown={(e) => {
                                                    if (e.key === "Enter") {
                                                        e.preventDefault();
                                                        handleConfirmRename(folder);
                                                    } else if (e.key === "Escape") {
                                                        e.preventDefault();
                                                        handleCancelRename();
                                                    }
                                                }}
                                                onBlur={() => handleConfirmRename(folder)}
                                                className="min-w-0 flex-1 rounded border border-[#165dff] bg-white px-2 py-1 text-sm outline-none"
                                            />
                                            {savingFolder && <Loader2 className="size-4 shrink-0 animate-spin text-[#86909c]" />}
                                        </>
                                    ) : (
                                        <>
                                            <span className="flex-1 truncate">{folder.name}</span>
                                            {/* Rename this folder */}
                                            <button
                                                type="button"
                                                onClick={(e) => { e.stopPropagation(); handleStartRename(folder); }}
                                                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#165dff]/10 transition-opacity"
                                                title={localize("com_knowledge.rename")}
                                            >
                                                <Pencil className="size-4 text-[#4e5969]" />
                                            </button>
                                            {/* Navigate into sub-folder */}
                                            <button
                                                type="button"
                                                onClick={(e) => { e.stopPropagation(); handleNavigateInto(folder); }}
                                                className="opacity-0 group-hover:opacity-100 p-0.5 rounded hover:bg-[#165dff]/10 transition-opacity"
                                                title={localize("com_knowledge.folder")}
                                            >
                                                <ChevronRight className="size-4 text-[#4e5969]" />
                                            </button>
                                        </>
                                    )}
                                </div>
                            );
                        })
```

- [ ] **Step 4: 运行测试，确认通过**

Run: `npx jest src/pages/knowledge/SpaceDetail/MoveFolderDialog.rename.test.tsx`
Expected: PASS —— 6 个用例全绿。

- [ ] **Step 5: Lint 改动文件**

Run: `npx eslint src/pages/knowledge/SpaceDetail/MoveFolderDialog.tsx src/pages/knowledge/SpaceDetail/MoveFolderDialog.rename.test.tsx`
Expected: 无 error（如仅有既有风格 warning 可忽略，但不得引入新 error）。

- [ ] **Step 6: 提交**

```bash
git add src/frontend/client/src/pages/knowledge/SpaceDetail/MoveFolderDialog.tsx \
        src/frontend/client/src/pages/knowledge/SpaceDetail/MoveFolderDialog.rename.test.tsx
git commit -m "feat(knowledge): support renaming folders in the move-to dialog"
```

---

## 手动验证（可选，建议在合并前跑一次真实 UI）

1. 进入某知识库空间详情页，对任一文件/文件夹点"移动到"。
2. 弹窗内 hover 一个已有文件夹 → 右侧出现铅笔与进入箭头两个按钮。
3. 点铅笔 → 该行变输入框，全选当前名；改名后回车/失焦 → 名称就地更新，左侧目录树同步。
4. Portal 门户内的知识库工作台重复上述流程 → 宿主文件列表中的该文件夹名同步更新。
5. Escape 取消不改名；点铅笔不会把该行选中为移动目标（底部"确认"仍需另行选目标才可点）。

## Self-Review 记录

- **Spec coverage:** 交互(铅笔/内联/Enter-blur/Escape)、提交逻辑(空名/同名跳过、成功刷新、拦截器报错、防双提交)、状态建模(方案 A 三个新状态 + 四处重置/互斥)、渲染改造、边界(stopPropagation、重命名态不选目标、moving 项已过滤、根目录不涉及)、测试计划 —— 均由 Task 1 的 Step 3b–3e 与测试 Step 1 覆盖。
- **Placeholder scan:** 无 TBD/TODO；所有代码步均给出完整代码。
- **Type consistency:** `handleStartRename`/`handleConfirmRename` 形参为 `KnowledgeFile`；`renameFolderApi(spaceId, folder.id, name)` 与签名 `(space_id, folder_id, name)` 一致；`renamingId: string | null` 与 `folder.id: string` 比较一致；复用 `savingFolder` 作为提交中反馈（新建/重命名互斥，无冲突）。
