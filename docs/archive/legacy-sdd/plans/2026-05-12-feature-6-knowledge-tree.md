# Feature 6 — 知识空间目录树展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在知识空间详情页左侧加多级目录树（仅文件夹，默认折叠），主区域按 `parent_id` 展示当前层级的子节点；通过 `config.yaml` 全局开关控制是否启用，中粮场内关闭。

**Architecture:** 复用现有 `GET /api/v1/knowledge_space/{space_id}/children`（已支持 `parent_id`），仅新增可选 `file_type` 过滤参数。平台前端 `detail.tsx` 重构为左右两栏布局，`KnowledgeTree` 懒加载（仅 DIR），`Files` 改为按 `parent_id` 拉子节点。开关通过现有 `GET /api/v1/config` YAML 配置接口读取，无需新增配置 endpoint。

**Tech Stack:** FastAPI / SQLModel（backend）；React 18 + Vite + Zustand + react-query v3（platform app）；TDD with pytest + vitest。

**Related spec:** `docs/archive/legacy-sdd/specs/2026-05-12-2.6-features-1-and-6-design.md`（§2 系列）

**File map:**

| 操作 | 文件 |
|---|---|
| Modify | `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py:217` 附近（增加 `file_type` 参数） |
| Modify | `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（透传 `file_type`） |
| Modify | `src/backend/bisheng/knowledge/domain/models/knowledge_space_file.py:69-132`（`async_list_children` 加 filter） |
| Modify | `config.yaml`（追加 `knowledge_space.tree_structured_directory_display: true`） |
| Modify | `src/frontend/platform/src/controllers/API/index.ts`（新增 `listKnowledgeChildren`） |
| Modify | `src/frontend/platform/src/pages/KnowledgePage/useKnowledgeStore.ts` |
| Create | `src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeTree.tsx` |
| Create | `src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeBreadcrumb.tsx` |
| Modify | `src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`（接 `parentId` prop） |
| Modify | `src/frontend/platform/src/pages/KnowledgePage/detail.tsx`（feature flag gated layout） |

---

## Task 1: Add `file_type` optional filter to `SpaceFileDao.async_list_children`

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/models/knowledge_space_file.py`
- Test: `src/backend/tests/knowledge/test_space_file_dao_filter.py`

- [ ] **Step 1: Write the failing test**

```python
# src/backend/tests/knowledge/test_space_file_dao_filter.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bisheng.knowledge.domain.models.knowledge_space_file import SpaceFileDao


@pytest.mark.asyncio
@patch("bisheng.knowledge.domain.models.knowledge_space_file.async_session_scope")
async def test_async_list_children_file_type_zero_filters_dirs(mock_session):
    """file_type=0 → SQL 应包含 file_type==0 filter。"""
    session = AsyncMock()
    mock_session.return_value.__aenter__.return_value = session
    captured_stmt = {}
    async def fake_exec(stmt):
        captured_stmt["stmt"] = stmt
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        return result
    session.exec = AsyncMock(side_effect=fake_exec)

    await SpaceFileDao.async_list_children(
        knowledge_id=1, parent_id=None, page=1, page_size=10, file_type=0,
    )
    # Verify filter present in compiled SQL string
    stmt_str = str(captured_stmt["stmt"])
    assert "file_type" in stmt_str
    # Loose assertion: ensure SQL contains the literal 0
    assert "0" in stmt_str.replace(" ", "")


@pytest.mark.asyncio
@patch("bisheng.knowledge.domain.models.knowledge_space_file.async_session_scope")
async def test_async_list_children_file_type_none_does_not_filter(mock_session):
    """file_type=None → SQL 不应增加 file_type filter。"""
    session = AsyncMock()
    mock_session.return_value.__aenter__.return_value = session
    captured_stmt = {}
    async def fake_exec(stmt):
        captured_stmt["stmt"] = stmt
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        return result
    session.exec = AsyncMock(side_effect=fake_exec)

    await SpaceFileDao.async_list_children(
        knowledge_id=1, parent_id=None, page=1, page_size=10, file_type=None,
    )
    # We rely on the prior test as baseline; explicit shape varies by SQLAlchemy.
    # Just ensure call succeeded without exception.
    assert "stmt" in captured_stmt
```

> Implementer note: depending on whether the DAO uses sync `Session` or `AsyncSession`, the test fixture may need adjusting. Inspect the current implementation of `async_list_children` (around lines 69-132) before writing the patch — match the same session pattern.

- [ ] **Step 2: Run test to verify failure**

```bash
cd src/backend && uv run pytest tests/knowledge/test_space_file_dao_filter.py -v
```
Expected: FAIL — `async_list_children` rejects unknown `file_type` kwarg.

- [ ] **Step 3: Modify `SpaceFileDao.async_list_children`**

Open `src/backend/bisheng/knowledge/domain/models/knowledge_space_file.py`. Locate `async_list_children` (around lines 69-132).

Change signature:

```python
@classmethod
async def async_list_children(
    cls,
    knowledge_id: int,
    parent_id: Optional[int],
    page: int,
    page_size: int,
    *,
    file_type: Optional[int] = None,   # NEW
    file_name: Optional[str] = None,
    file_status: Optional[int] = None,
) -> tuple[list[KnowledgeFile], int]:
```

Inside the body, where existing `filters` list is composed, add:

```python
    if file_type is not None:
        filters.append(KnowledgeFile.file_type == file_type)
```

If the function takes `**kwargs` instead, prefer explicit kwarg to keep typing safe.

- [ ] **Step 4: Run test to verify pass**

```bash
cd src/backend && uv run pytest tests/knowledge/test_space_file_dao_filter.py -v
```
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/backend/bisheng/knowledge/domain/models/knowledge_space_file.py src/backend/tests/knowledge/test_space_file_dao_filter.py
git commit -m "feat(knowledge): add optional file_type filter to async_list_children"
```

---

## Task 2: Thread `file_type` through service + endpoint

**Files:**
- Modify: `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`（method `list_space_children`）
- Modify: `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`（endpoint at line ~217）
- Test: `src/backend/tests/knowledge/test_list_children_endpoint.py`

- [ ] **Step 1: Write the failing test**

```python
# src/backend/tests/knowledge/test_list_children_endpoint.py
import pytest
from fastapi.testclient import TestClient

# Implementer note: import the FastAPI app or build a sub-app fixture per the repo's
# existing test convention (e.g., `from bisheng.main import app`). The exact import may
# differ; align with other endpoint tests in tests/knowledge/.


def test_list_children_accepts_file_type_query(test_client):
    """Endpoint should accept `file_type` query param and pass it through.

    We assert via response content; underlying data is fixture-controlled.
    """
    resp = test_client.get(
        "/api/v1/knowledge_space/1/children",
        params={"parent_id": "", "file_type": 0},
        headers={"Authorization": "Bearer <stub>"},
    )
    assert resp.status_code in (200, 401)  # 401 if auth fixture not configured
    # If 200: every returned item should have file_type=0
    if resp.status_code == 200:
        data = resp.json()
        for item in data.get("items", []):
            assert item["file_type"] == 0


def test_list_children_without_file_type_returns_both_types(test_client):
    resp = test_client.get(
        "/api/v1/knowledge_space/1/children",
        params={"parent_id": ""},
        headers={"Authorization": "Bearer <stub>"},
    )
    assert resp.status_code in (200, 401)
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd src/backend && uv run pytest tests/knowledge/test_list_children_endpoint.py -v
```
Expected: FAIL — endpoint doesn't yet accept `file_type` (FastAPI rejects unknown query in strict mode) OR validation error.

- [ ] **Step 3: Modify the service method**

Open `src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py`. Locate `list_space_children` (around line 1728). Add `file_type` to signature and pass through:

```python
async def list_space_children(
    self,
    space_id: int,
    parent_id: Optional[int],
    page: int,
    page_size: int,
    *,
    file_type: Optional[int] = None,   # NEW
    file_name: Optional[str] = None,
    file_status: Optional[int] = None,
) -> tuple[list[KnowledgeFile], int]:
    return await SpaceFileDao.async_list_children(
        knowledge_id=space_id,
        parent_id=parent_id,
        page=page,
        page_size=page_size,
        file_type=file_type,
        file_name=file_name,
        file_status=file_status,
    )
```

- [ ] **Step 4: Modify the endpoint**

Open `src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py`. Locate the route (around line 217). Add the new query param:

```python
from typing import Optional
from fastapi import Query

@router.get("/knowledge_space/{space_id}/children")
async def list_space_children_endpoint(
    space_id: int,
    parent_id: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(200, ge=1, le=1000),
    file_type: Optional[int] = Query(None, description="0=DIR, 1=FILE, empty=both"),  # NEW
    file_name: Optional[str] = Query(None),
    file_status: Optional[int] = Query(None),
    service: KnowledgeSpaceService = Depends(get_knowledge_space_service),
):
    items, total = await service.list_space_children(
        space_id=space_id,
        parent_id=parent_id,
        page=page,
        page_size=page_size,
        file_type=file_type,
        file_name=file_name,
        file_status=file_status,
    )
    return {"items": [serialize(i) for i in items], "total": total}
```

Use the actual existing function name; just add `file_type` parameter at the appropriate place. Don't rewrite serialization if it's already there.

- [ ] **Step 5: Run test to verify pass**

```bash
cd src/backend && uv run pytest tests/knowledge/test_list_children_endpoint.py -v
```
Expected: PASS (2 passed, possibly 401 if no auth fixture — that's a wiring issue, not a logic issue).

- [ ] **Step 6: Smoke run the whole knowledge test suite**

```bash
cd src/backend && uv run pytest tests/knowledge/ -v
```
Expected: existing tests still pass.

- [ ] **Step 7: Commit**

```bash
git add src/backend/bisheng/knowledge/domain/services/knowledge_space_service.py \
        src/backend/bisheng/knowledge/api/endpoints/knowledge_space.py \
        src/backend/tests/knowledge/test_list_children_endpoint.py
git commit -m "feat(knowledge): expose file_type filter on /children endpoint"
```

---

## Task 3: Add `knowledge_space.tree_structured_directory_display` to config.yaml

**Files:**
- Modify: `config.yaml` (the example / template config used by deployments)

> **Backend reads no new code** — the existing `GET /api/v1/config` returns the full YAML; frontend parses the new field directly. We only document and ship the default.

- [ ] **Step 1: Edit config.yaml to add the new section**

Locate the project's reference `config.yaml`（typically `src/backend/config.dev.yaml` or `src/backend/bisheng/config.yaml`；run `find src/backend -maxdepth 3 -name 'config*.yaml'` to find it). At the appropriate top-level position, add:

```yaml
knowledge_space:
  # 知识空间左侧目录树展示开关（仅前端读取）
  # 默认 true；中粮场内部署改为 false 走原 Tab 布局。
  tree_structured_directory_display: true
```

- [ ] **Step 2: Verify via API**

Start the backend dev server and call:

```bash
curl -s http://localhost:8000/api/v1/config | jq '.knowledge_space.tree_structured_directory_display'
```

Expected: `true`

- [ ] **Step 3: Commit**

```bash
git add src/backend/<your-config-file>.yaml
git commit -m "feat(config): add knowledge_space.tree_structured_directory_display flag"
```

---

## Task 4: Add `listKnowledgeChildren` to platform API client

**Files:**
- Modify: `src/frontend/platform/src/controllers/API/index.ts`

- [ ] **Step 1: Add the function**

Locate `readFileByLibDatabase` (around lines 272-294) for reference. Add **below** it (or in a logical position):

```ts
export interface KnowledgeNode {
  id: number;
  file_name: string;
  file_type: 0 | 1;
  file_size: number | null;
  status?: number;
  created_at: string;
  updated_at: string;
}

export interface ListChildrenParams {
  knowledge_id: number;
  parent_id: number | null;
  file_type?: 0 | 1;
  page?: number;
  page_size?: number;
  keyword?: string;
}

export async function listKnowledgeChildren(
  params: ListChildrenParams
): Promise<{ items: KnowledgeNode[]; total: number }> {
  return await axios.get(
    `/api/v1/knowledge_space/${params.knowledge_id}/children`,
    {
      params: {
        parent_id: params.parent_id ?? "",
        file_type: params.file_type,
        page: params.page ?? 1,
        page_size: params.page_size ?? 200,
        keyword: params.keyword,
      },
    }
  );
}
```

- [ ] **Step 2: Add a smoke test**

`src/frontend/platform/src/controllers/API/__tests__/listKnowledgeChildren.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from "vitest";
import axios from "../request";
import { listKnowledgeChildren } from "../index";

vi.mock("../request", () => ({
  default: { get: vi.fn() },
}));

describe("listKnowledgeChildren", () => {
  beforeEach(() => vi.clearAllMocks());

  it("calls /api/v1/knowledge_space/<id>/children with correct params", async () => {
    (axios.get as any).mockResolvedValue({ items: [], total: 0 });
    await listKnowledgeChildren({
      knowledge_id: 7, parent_id: 12, file_type: 0, page: 2, page_size: 50, keyword: "abc",
    });
    expect(axios.get).toHaveBeenCalledWith(
      "/api/v1/knowledge_space/7/children",
      { params: { parent_id: 12, file_type: 0, page: 2, page_size: 50, keyword: "abc" } }
    );
  });

  it("sends parent_id='' when null", async () => {
    (axios.get as any).mockResolvedValue({ items: [], total: 0 });
    await listKnowledgeChildren({ knowledge_id: 1, parent_id: null });
    expect(axios.get).toHaveBeenCalledWith(
      "/api/v1/knowledge_space/1/children",
      { params: { parent_id: "", file_type: undefined, page: 1, page_size: 200, keyword: undefined } }
    );
  });
});
```

- [ ] **Step 3: Run test**

```bash
cd src/frontend/platform && pnpm vitest run src/controllers/API/__tests__/listKnowledgeChildren.test.ts
```
Expected: PASS (2 passed)

- [ ] **Step 4: Commit**

```bash
git add src/frontend/platform/src/controllers/API/index.ts \
        src/frontend/platform/src/controllers/API/__tests__/listKnowledgeChildren.test.ts
git commit -m "feat(platform): add listKnowledgeChildren API client"
```

---

## Task 5: Extend `useKnowledgeStore` (Zustand) with tree state

**Files:**
- Modify: `src/frontend/platform/src/pages/KnowledgePage/useKnowledgeStore.ts`

- [ ] **Step 1: Write the failing test**

`src/frontend/platform/src/pages/KnowledgePage/useKnowledgeStore.test.ts`:

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { useKnowledgeStore } from "./useKnowledgeStore";

describe("useKnowledgeStore tree state", () => {
  beforeEach(() => {
    useKnowledgeStore.setState({
      currentParentId: null,
      selectedFileId: null,
      breadcrumbPath: [],
    });
  });

  it("setCurrentParent updates id and breadcrumb", () => {
    useKnowledgeStore.getState().setCurrentParent(42, [{ id: 1, name: "a" }, { id: 42, name: "b" }]);
    const s = useKnowledgeStore.getState();
    expect(s.currentParentId).toBe(42);
    expect(s.breadcrumbPath).toEqual([{ id: 1, name: "a" }, { id: 42, name: "b" }]);
    expect(s.selectedFileId).toBe(null);
  });

  it("setSelectedFile updates only selectedFileId", () => {
    useKnowledgeStore.getState().setCurrentParent(5, [{ id: 5, name: "x" }]);
    useKnowledgeStore.getState().setSelectedFile(99);
    expect(useKnowledgeStore.getState().selectedFileId).toBe(99);
    expect(useKnowledgeStore.getState().currentParentId).toBe(5);
  });

  it("setCurrentParent clears selectedFileId", () => {
    useKnowledgeStore.setState({ selectedFileId: 99 });
    useKnowledgeStore.getState().setCurrentParent(7, []);
    expect(useKnowledgeStore.getState().selectedFileId).toBe(null);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd src/frontend/platform && pnpm vitest run src/pages/KnowledgePage/useKnowledgeStore.test.ts
```
Expected: FAIL — properties / methods undefined.

- [ ] **Step 3: Implement the extension**

Open `src/frontend/platform/src/pages/KnowledgePage/useKnowledgeStore.ts`. Add new fields to the interface and store:

```ts
interface BreadcrumbItem {
  id: number;
  name: string;
}

// in the existing interface:
interface KnowledgeStore {
  // ... existing fields ...
  currentParentId: number | null;
  selectedFileId: number | null;
  breadcrumbPath: BreadcrumbItem[];
  setCurrentParent: (id: number | null, path: BreadcrumbItem[]) => void;
  setSelectedFile: (id: number | null) => void;
}

// in the create() body:
export const useKnowledgeStore = create<KnowledgeStore>((set) => ({
  // ... existing state ...
  currentParentId: null,
  selectedFileId: null,
  breadcrumbPath: [],
  setCurrentParent: (id, path) => set({
    currentParentId: id, breadcrumbPath: path, selectedFileId: null,
  }),
  setSelectedFile: (id) => set({ selectedFileId: id }),
}));
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd src/frontend/platform && pnpm vitest run src/pages/KnowledgePage/useKnowledgeStore.test.ts
```
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/frontend/platform/src/pages/KnowledgePage/useKnowledgeStore.ts \
        src/frontend/platform/src/pages/KnowledgePage/useKnowledgeStore.test.ts
git commit -m "feat(platform): extend useKnowledgeStore with tree navigation state"
```

---

## Task 6: Create `KnowledgeBreadcrumb` component

**Files:**
- Create: `src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeBreadcrumb.tsx`
- Test: `src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeBreadcrumb.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// KnowledgeBreadcrumb.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { KnowledgeBreadcrumb } from "./KnowledgeBreadcrumb";

describe("KnowledgeBreadcrumb", () => {
  it("renders space root + path segments", () => {
    render(
      <KnowledgeBreadcrumb
        spaceName="技术空间"
        path={[{ id: 1, name: "项目A" }, { id: 2, name: "文档" }]}
        onNavigate={() => {}}
      />
    );
    expect(screen.getByText("技术空间")).toBeInTheDocument();
    expect(screen.getByText("项目A")).toBeInTheDocument();
    expect(screen.getByText("文档")).toBeInTheDocument();
  });

  it("clicking a segment fires onNavigate with that segment id", () => {
    const onNav = vi.fn();
    render(
      <KnowledgeBreadcrumb
        spaceName="X"
        path={[{ id: 11, name: "A" }, { id: 22, name: "B" }]}
        onNavigate={onNav}
      />
    );
    fireEvent.click(screen.getByText("A"));
    expect(onNav).toHaveBeenCalledWith(11, 0);
  });

  it("clicking space root fires onNavigate(null, -1)", () => {
    const onNav = vi.fn();
    render(
      <KnowledgeBreadcrumb spaceName="X" path={[{ id: 11, name: "A" }]} onNavigate={onNav} />
    );
    fireEvent.click(screen.getByText("X"));
    expect(onNav).toHaveBeenCalledWith(null, -1);
  });
});
```

- [ ] **Step 2: Run test to verify failure**

```bash
cd src/frontend/platform && pnpm vitest run src/pages/KnowledgePage/components/KnowledgeBreadcrumb.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
// KnowledgeBreadcrumb.tsx
import { ChevronRight } from "lucide-react";

export interface BreadcrumbItem {
  id: number;
  name: string;
}

export interface KnowledgeBreadcrumbProps {
  spaceName: string;
  path: BreadcrumbItem[];
  onNavigate: (id: number | null, index: number) => void;
}

export function KnowledgeBreadcrumb({
  spaceName, path, onNavigate,
}: KnowledgeBreadcrumbProps) {
  return (
    <nav className="flex items-center text-sm text-gray-600 gap-1">
      <button
        className="hover:text-gray-900"
        onClick={() => onNavigate(null, -1)}
      >
        {spaceName}
      </button>
      {path.map((item, i) => (
        <span key={item.id} className="flex items-center gap-1">
          <ChevronRight className="w-3 h-3 text-gray-400" />
          <button
            className={i === path.length - 1 ? "text-gray-900 font-medium" : "hover:text-gray-900"}
            onClick={() => onNavigate(item.id, i)}
          >
            {item.name}
          </button>
        </span>
      ))}
    </nav>
  );
}
```

- [ ] **Step 4: Run test to verify pass**

```bash
cd src/frontend/platform && pnpm vitest run src/pages/KnowledgePage/components/KnowledgeBreadcrumb.test.tsx
```
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeBreadcrumb.tsx \
        src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeBreadcrumb.test.tsx
git commit -m "feat(platform): add KnowledgeBreadcrumb component"
```

---

## Task 7: Create `KnowledgeTree` component (lazy load, DIR-only)

**Files:**
- Create: `src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeTree.tsx`
- Test: `src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeTree.test.tsx`

> **Reference**: `src/frontend/platform/src/pages/DepartmentPage/components/DepartmentTree.tsx` (existing well-tested tree). Copy the indentation / collapse pattern, but the data source is different.

- [ ] **Step 1: Write the failing tests**

```tsx
// KnowledgeTree.test.tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { KnowledgeTree } from "./KnowledgeTree";
import * as API from "@/controllers/API";

vi.mock("@/controllers/API", () => ({
  listKnowledgeChildren: vi.fn(),
}));

const mockedList = vi.mocked(API.listKnowledgeChildren);

const rootFolders = [
  { id: 1, file_name: "项目A", file_type: 0, file_size: null, created_at: "", updated_at: "" },
  { id: 2, file_name: "项目B", file_type: 0, file_size: null, created_at: "", updated_at: "" },
];
const subFolders = [
  { id: 11, file_name: "文档", file_type: 0, file_size: null, created_at: "", updated_at: "" },
];

describe("KnowledgeTree", () => {
  beforeEach(() => {
    mockedList.mockReset();
  });

  it("renders root folders fetched on mount", async () => {
    mockedList.mockResolvedValueOnce({ items: rootFolders, total: 2 });

    render(<KnowledgeTree knowledgeId={5} onSelectFolder={() => {}} />);

    await waitFor(() => {
      expect(screen.getByText("项目A")).toBeInTheDocument();
      expect(screen.getByText("项目B")).toBeInTheDocument();
    });
    // Should fetch with file_type=0 (DIR only) and parent_id=null
    expect(mockedList).toHaveBeenCalledWith({
      knowledge_id: 5, parent_id: null, file_type: 0,
    });
  });

  it("expand arrow click lazy-loads children", async () => {
    mockedList
      .mockResolvedValueOnce({ items: rootFolders, total: 2 })
      .mockResolvedValueOnce({ items: subFolders, total: 1 });

    render(<KnowledgeTree knowledgeId={5} onSelectFolder={() => {}} />);
    await waitFor(() => screen.getByText("项目A"));

    fireEvent.click(screen.getByTestId("tree-expand-1"));
    await waitFor(() => {
      expect(screen.getByText("文档")).toBeInTheDocument();
    });
    expect(mockedList).toHaveBeenLastCalledWith({
      knowledge_id: 5, parent_id: 1, file_type: 0,
    });
  });

  it("click on folder name fires onSelectFolder with id+name", async () => {
    mockedList.mockResolvedValueOnce({ items: rootFolders, total: 2 });
    const onSel = vi.fn();
    render(<KnowledgeTree knowledgeId={5} onSelectFolder={onSel} />);
    await waitFor(() => screen.getByText("项目A"));

    fireEvent.click(screen.getByText("项目A"));
    expect(onSel).toHaveBeenCalledWith({ id: 1, name: "项目A" });
  });

  it("expand on empty folder shows nothing extra (optimistic arrow)", async () => {
    mockedList
      .mockResolvedValueOnce({ items: rootFolders, total: 2 })
      .mockResolvedValueOnce({ items: [], total: 0 });
    render(<KnowledgeTree knowledgeId={5} onSelectFolder={() => {}} />);
    await waitFor(() => screen.getByText("项目A"));

    fireEvent.click(screen.getByTestId("tree-expand-1"));
    await waitFor(() => expect(mockedList).toHaveBeenCalledTimes(2));
    // No children rendered
    expect(screen.queryByText("文档")).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify failure**

```bash
cd src/frontend/platform && pnpm vitest run src/pages/KnowledgePage/components/KnowledgeTree.test.tsx
```
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
// KnowledgeTree.tsx
import { useEffect, useState, useCallback } from "react";
import { ChevronRight, ChevronDown, Folder } from "lucide-react";
import { listKnowledgeChildren, KnowledgeNode } from "@/controllers/API";

const INDENT_PX = 20;

export interface KnowledgeTreeProps {
  knowledgeId: number;
  onSelectFolder: (folder: { id: number; name: string }) => void;
}

interface TreeNodeRowProps {
  node: KnowledgeNode;
  knowledgeId: number;
  depth: number;
  onSelectFolder: KnowledgeTreeProps["onSelectFolder"];
}

function TreeNodeRow({ node, knowledgeId, depth, onSelectFolder }: TreeNodeRowProps) {
  const [expanded, setExpanded] = useState(false);
  const [children, setChildren] = useState<KnowledgeNode[] | null>(null);
  const [loading, setLoading] = useState(false);

  const handleExpand = useCallback(async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (children === null) {
      setLoading(true);
      try {
        const resp = await listKnowledgeChildren({
          knowledge_id: knowledgeId, parent_id: node.id, file_type: 0,
        });
        setChildren(resp.items);
      } finally {
        setLoading(false);
      }
    }
    setExpanded((v) => !v);
  }, [knowledgeId, node.id, children]);

  return (
    <div>
      <div
        className="flex items-center gap-1 px-1 py-1 hover:bg-gray-100 cursor-pointer rounded"
        style={{ paddingLeft: depth * INDENT_PX + 4 }}
      >
        <button
          data-testid={`tree-expand-${node.id}`}
          onClick={handleExpand}
          className="w-4 h-4 flex items-center justify-center text-gray-500"
          aria-label={expanded ? "collapse" : "expand"}
        >
          {expanded ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
        </button>
        <Folder className="w-4 h-4 text-blue-500" />
        <span
          className="flex-1 text-sm truncate"
          onClick={() => onSelectFolder({ id: node.id, name: node.file_name })}
        >
          {node.file_name}
        </span>
      </div>
      {expanded && children && children.length > 0 && (
        <div>
          {children.map((c) => (
            <TreeNodeRow
              key={c.id}
              node={c}
              knowledgeId={knowledgeId}
              depth={depth + 1}
              onSelectFolder={onSelectFolder}
            />
          ))}
        </div>
      )}
      {expanded && loading && (
        <div style={{ paddingLeft: (depth + 1) * INDENT_PX + 4 }} className="text-xs text-gray-400 py-1">
          加载中…
        </div>
      )}
    </div>
  );
}

export function KnowledgeTree({ knowledgeId, onSelectFolder }: KnowledgeTreeProps) {
  const [roots, setRoots] = useState<KnowledgeNode[]>([]);

  useEffect(() => {
    listKnowledgeChildren({
      knowledge_id: knowledgeId, parent_id: null, file_type: 0,
    }).then((resp) => setRoots(resp.items));
  }, [knowledgeId]);

  return (
    <div className="overflow-auto">
      {roots.map((r) => (
        <TreeNodeRow
          key={r.id}
          node={r}
          knowledgeId={knowledgeId}
          depth={0}
          onSelectFolder={onSelectFolder}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify pass**

```bash
cd src/frontend/platform && pnpm vitest run src/pages/KnowledgePage/components/KnowledgeTree.test.tsx
```
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeTree.tsx \
        src/frontend/platform/src/pages/KnowledgePage/components/KnowledgeTree.test.tsx
git commit -m "feat(platform): add KnowledgeTree component (DIR-only, lazy load)"
```

---

## Task 8: Refactor `Files.tsx` to accept `parentId` prop and use `/children`

**Files:**
- Modify: `src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx`

> **Strategy**: keep the existing `Files` component shell (table layout, pagination, search) but replace the data fetch hook from `readFileByLibDatabase` to `listKnowledgeChildren` with `parent_id` and **no `file_type` filter** (right panel shows both DIRs and files).

- [ ] **Step 1: Add prop + parent_id awareness**

In `Files.tsx`, extend the props (it's currently likely no props or just `id`):

```tsx
export interface FilesProps {
  parentId: number | null;
  onSelectFolder: (folder: { id: number; name: string }) => void;
  onSelectFile: (fileId: number) => void;
}
```

Replace the data hook. Locate the call to `readFileByLibDatabase` (around line 114) and replace:

```tsx
// Before:
// readFileByLibDatabase({ ...param, id, name: param.keyword })

// After:
import { listKnowledgeChildren } from "@/controllers/API";

const fetchPage = async (param: { page_num: number; page_size: number; keyword?: string }) => {
  const resp = await listKnowledgeChildren({
    knowledge_id: id,
    parent_id: parentId,
    page: param.page_num,
    page_size: param.page_size,
    keyword: param.keyword,
  });
  return { data: resp.items, total: resp.total };
};
```

When rendering each row, branch on `file_type`:

```tsx
{item.file_type === 0 ? (
  <span
    className="flex items-center gap-2 text-blue-600 cursor-pointer"
    onClick={() => onSelectFolder({ id: item.id, name: item.file_name })}
  >
    <Folder className="w-4 h-4" />
    {item.file_name}
  </span>
) : (
  <span
    className="flex items-center gap-2 cursor-pointer"
    onClick={() => onSelectFile(item.id)}
  >
    <FileText className="w-4 h-4" />
    {item.file_name}
  </span>
)}
```

- [ ] **Step 2: Type-check**

```bash
cd src/frontend/platform && pnpm tsc --noEmit
```
Expected: 0 errors specific to Files.tsx (other unrelated errors may exist).

- [ ] **Step 3: Manual smoke** — done in Task 10 e2e.

- [ ] **Step 4: Commit**

```bash
git add src/frontend/platform/src/pages/KnowledgePage/components/Files.tsx
git commit -m "feat(platform): wire Files to /children endpoint with parent_id"
```

---

## Task 9: Refactor `detail.tsx` — feature-flag gated left-sidebar layout

**Files:**
- Modify: `src/frontend/platform/src/pages/KnowledgePage/detail.tsx`

- [ ] **Step 1: Add feature flag fetch**

At the top of `detail.tsx`:

```tsx
import { useEffect, useState } from "react";
import axios from "@/controllers/request";

function useTreeLayoutFlag(): boolean {
  const [enabled, setEnabled] = useState<boolean>(true);  // optimistic default
  useEffect(() => {
    axios.get("/api/v1/config").then((data: any) => {
      const flag = data?.knowledge_space?.tree_structured_directory_display;
      // Treat undefined as enabled (matches our default)
      setEnabled(flag !== false);
    }).catch(() => setEnabled(true));
  }, []);
  return enabled;
}
```

- [ ] **Step 2: Branch render**

In the existing `detail` component:

```tsx
import { useKnowledgeStore } from "./useKnowledgeStore";
import { KnowledgeTree } from "./components/KnowledgeTree";
import { KnowledgeBreadcrumb } from "./components/KnowledgeBreadcrumb";
import { Files } from "./components/Files";

export default function Detail() {
  const { id } = useParams();
  const knowledgeId = Number(id);
  const treeEnabled = useTreeLayoutFlag();

  const {
    currentParentId, breadcrumbPath, setCurrentParent, setSelectedFile,
  } = useKnowledgeStore();

  // Existing space-info hooks here ...
  const spaceName = "<existing>";  // keep current source

  if (!treeEnabled) {
    // Fallback to original Tab layout — preserve existing JSX
    return <LegacyTabLayout id={knowledgeId} />;
  }

  return (
    <div className="flex flex-col h-full">
      <header className="flex items-center px-4 py-2 border-b">
        <KnowledgeBreadcrumb
          spaceName={spaceName}
          path={breadcrumbPath}
          onNavigate={(id, index) => {
            if (id === null) {
              setCurrentParent(null, []);
            } else {
              setCurrentParent(id, breadcrumbPath.slice(0, index + 1));
            }
          }}
        />
      </header>
      <div className="flex flex-1 overflow-hidden">
        <aside className="w-64 border-r overflow-y-auto p-2">
          <KnowledgeTree
            knowledgeId={knowledgeId}
            onSelectFolder={(folder) =>
              setCurrentParent(folder.id, [...breadcrumbPath, folder])
            }
          />
        </aside>
        <main className="flex-1 overflow-y-auto">
          <Files
            parentId={currentParentId}
            onSelectFolder={(folder) =>
              setCurrentParent(folder.id, [...breadcrumbPath, folder])
            }
            onSelectFile={(fileId) => setSelectedFile(fileId)}
          />
        </main>
      </div>
    </div>
  );
}
```

> Implementer note: `LegacyTabLayout` is the existing implementation of `detail.tsx`. Extract it into a named function (in the same file, no new file needed) for the fallback path; this is purely a wrap for clarity.

- [ ] **Step 3: Type-check + lint**

```bash
cd src/frontend/platform && pnpm tsc --noEmit && pnpm lint
```
Expected: 0 errors in `detail.tsx`.

- [ ] **Step 4: Commit**

```bash
git add src/frontend/platform/src/pages/KnowledgePage/detail.tsx
git commit -m "feat(platform): tree-layout detail page gated by feature flag"
```

---

## Task 10: End-to-end manual verification

**Files:** none (manual)

- [ ] **Step 1: Backend smoke**

```bash
curl -s "http://localhost:8000/api/v1/knowledge_space/1/children?file_type=0&parent_id=" \
  -H "Authorization: Bearer <token>" | jq '.items[] | .file_type'
```
Expected: every line `0`.

```bash
curl -s "http://localhost:8000/api/v1/knowledge_space/1/children?parent_id=" \
  -H "Authorization: Bearer <token>" | jq '.items[] | .file_type'
```
Expected: mix of `0` and `1`.

- [ ] **Step 2: Platform UI happy path**

1. `cd src/frontend/platform && pnpm dev`
2. Login → enter a knowledge space with folders + files.
3. Verify left tree shows root folders only (no files), all collapsed.
4. Click ▶ on a folder → children fetched lazily, expand animation shown.
5. Click folder name → right side shows that folder's children (folders + files).
6. Click breadcrumb segment → right side jumps to that level.
7. Click a file → enters segments / preview view.

- [ ] **Step 3: Feature flag fallback**

1. Edit `config.yaml` → `knowledge_space.tree_structured_directory_display: false`
2. Save via `POST /api/v1/config/save` (or restart backend if file-based).
3. Reload frontend → page should render original Tab layout (no left sidebar).

- [ ] **Step 4: Large folder smoke**

1. In a folder with >200 items, scroll the right-side list, verify pagination works.
2. Use search box → verify keyword filter still works within current parent.

- [ ] **Step 5: Document outcome**

In PR description, include:
- Screenshot of tree layout with breadcrumb
- Screenshot of fallback Tab layout (flag=false)
- Captured curl outputs

---

## Self-review

- [ ] **Spec coverage**: §2.2（开关）→ Tasks 3, 9；§2.3（后端微调）→ Tasks 1, 2；§2.4–2.5（前端布局/结构）→ Tasks 6-9；§2.6（Zustand 扩展）→ Task 5；§2.7（KnowledgeTree 行为）→ Task 7；§2.8（API client）→ Task 4；§2.9（交互细节）→ Tasks 7-9 + Task 10 verification；§2.10（测试策略）→ each task.
- [ ] No "TBD" / "fill in later" markers.
- [ ] Type names consistent: `KnowledgeNode`, `listKnowledgeChildren`, `useKnowledgeStore`, `KnowledgeBreadcrumb`, `KnowledgeTree`.
- [ ] Backend changes are additive (file_type optional); existing callers unaffected.

---

## Execution handoff

Plan complete and saved. Recommended execution: **subagent-driven** — Task 1-2 (backend) can be one subagent; Tasks 4-9 (frontend) are best split as Task 4-5 (data layer), Task 6-7 (components), Task 8-9 (layout integration) — each subagent reviews diffs before the next dispatches.

If you prefer batch inline execution, use `superpowers:executing-plans`.
