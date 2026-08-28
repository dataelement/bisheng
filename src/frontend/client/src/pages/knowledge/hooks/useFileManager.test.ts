/**
 * T026 — F027 §AC-17-client-补做 static guards for client SpaceDetail
 * infinite scroll.
 *
 * Why static rather than full behaviour test:
 *   `useFileManager` pulls in toast/i18n providers, query-string state, and
 *   chained useEffects that auto-load on mount. A faithful behaviour test
 *   would mock 6+ modules and still race on the auto-load effect. The
 *   critical invariants we need to protect from regression are textual —
 *   "page=1 replaces files, page>1 appends", "refresh poll doesn't advance
 *   the cursor chain", "SpaceDetail UI no longer imports PaginationBar".
 *   AST/source scan covers those without provider mocking.
 *
 * Behaviour-level testing of the append path is captured manually in the
 * F027 tasks.md §T022 checklist row for `client /workspace/knowledge/<id>`.
 */
import { readFileSync } from "fs";
import { join } from "path";

import { FileType, type KnowledgeFile } from "~/api/knowledge";

import {
  applyBatchDeleteDecision,
  applyBatchRenameDecision,
  applyDeleteDecision,
  applyRenameDecision,
  buildDirectMoveUndoEntries,
  isFileChangeMutationLocked,
  shouldRetryLegacyPartialMove,
} from "./fileMutationUtils";

const repoRoot = join(__dirname, "..", "..", "..", "..");

function read(rel: string): string {
  return readFileSync(join(repoRoot, rel), "utf8");
}

function file(id: string, name: string, type = FileType.PDF): KnowledgeFile {
  return {
    id,
    name,
    type,
    tags: [],
    path: name,
    spaceId: "101",
    createdAt: "",
    updatedAt: "",
  };
}

describe("knowledge file mutation decisions", () => {
  const original = [file("1", "old.pdf"), file("2", "folder", FileType.FOLDER), file("3", "keep.pdf")];

  it("renames only a direct item and keeps the old name while approval is pending", () => {
    expect(applyRenameDecision(original, "1", "new.pdf", { decision: "direct" })[0].name).toBe("new.pdf");
    expect(applyRenameDecision(original, "1", "new.pdf", { decision: "pending" })).toEqual(original);
  });

  it("removes only a direct delete and never optimistically removes a pending delete", () => {
    expect(applyDeleteDecision(original, "1", { decision: "direct" }).map((item) => item.id)).toEqual(["2", "3"]);
    expect(applyDeleteDecision(original, "1", { decision: "pending" })).toEqual(original);
  });

  it("keeps files and names unchanged for single-item invalid rename/delete decisions", () => {
    expect(applyRenameDecision(original, "1", "new.pdf", {
      decision: "invalid",
      errorMessage: "locked",
    })).toEqual(original);
    expect(applyDeleteDecision(original, "1", {
      decision: "invalid",
      errorMessage: "locked",
    })).toEqual(original);
  });

  it("keeps successful batch deletes when siblings are pending or invalid", () => {
    const next = applyBatchDeleteDecision(original, {
      completed: [{ id: 1, type: "file" }],
      pending: [{ id: 2, type: "folder" }],
      invalid: [{ id: 3, type: "file", errorMessage: "locked" }],
    });
    expect(next.map((item) => item.id)).toEqual(["2", "3"]);
  });

  it("updates only successful batch renames and preserves pending/invalid names", () => {
    const next = applyBatchRenameDecision(
      original,
      new Map([["1", "renamed.pdf"], ["2", "renamed-folder"], ["3", "invalid.pdf"]]),
      {
        completed: [{ id: 1, type: "file" }],
        pending: [{ id: 2, type: "folder" }],
        invalid: [{ id: 3, type: "file", errorMessage: "locked" }],
      },
    );
    expect(next.map((item) => item.name)).toEqual(["renamed.pdf", "folder", "keep.pdf"]);
  });

  it("blocks repeat mutations for both root and inherited approval locks", () => {
    const approval = {
      status: "pending" as const,
      action: "move" as const,
      instanceId: 8,
      requestId: 9,
      canApprove: false,
      inherited: false,
      rootResourceId: 1,
    };
    expect(isFileChangeMutationLocked({ ...original[0], fileChangeApproval: approval })).toBe(true);
    expect(isFileChangeMutationLocked({
      ...original[1],
      fileChangeApproval: { ...approval, inherited: true, rootResourceId: 2 },
    })).toBe(true);
    expect(isFileChangeMutationLocked(original[2])).toBe(false);
  });

  it("builds undo only for directly moved entries and derives old parents for the new response", () => {
    const moved = buildDirectMoveUndoEntries(
      [{ id: 1, type: "file" }],
      [{ ...original[0], parentId: "7" }, { ...original[1], parentId: "8" }],
      false,
    );
    expect(moved).toEqual([{ id: 1, type: "file", old_parent_id: 7, cross_space: false }]);
  });

  it("never offers undo for direct cross-space file and folder moves", () => {
    expect(buildDirectMoveUndoEntries(
      [{ id: 1, type: "file" }, { id: 2, type: "folder" }],
      original.slice(0, 2),
      true,
    )).toEqual([]);
  });

  it("only retries the legacy reject-all move shape, never a new partial-success response", () => {
    expect(shouldRetryLegacyPartialMove({
      moved: [], pending: [], invalid: [{ id: 3, type: "file", name: "x", reason: "name_conflict" }],
    })).toBe(true);
    expect(shouldRetryLegacyPartialMove({
      moved: [{ id: 1, type: "file" }], pending: [], invalid: [{ id: 3, type: "file", errorMessage: "locked" }],
    })).toBe(false);
  });
});

describe("useFileManager — F027 infinite-scroll guards", () => {
  const src = read("src/pages/knowledge/hooks/useFileManager.ts");

  it("declares nextSearchPage state to stitch search-path append batches", () => {
    expect(src).toMatch(/const\s+\[nextSearchPage,\s*setNextSearchPage\]\s*=\s*useState\(0\)/);
  });

  it("branches loadFiles by page number: page=1 replaces, page>1 appends", () => {
    // isAppending = page > 1 is the trigger; append uses functional setFiles(prev => [...prev, ...])
    expect(src).toMatch(/const\s+isAppending\s*=\s*page\s*>\s*1/);
    expect(src).toMatch(/setFiles\(prev\s*=>\s*\[\.\.\.prev,\s*\.\.\.filteredData\]\)/);
  });

  it("default path uses nextCursor on append, null on fresh load", () => {
    expect(src).toMatch(/cursor:\s*isAppending\s*\?\s*nextCursor\s*:\s*null/);
  });

  it("search path computes next page from nextSearchPage", () => {
    expect(src).toMatch(/isAppending\s*\?\s*nextSearchPage\s*\+\s*1\s*:\s*1/);
  });

  it("derives total from accumulated files + has_more (no per-batch setTotal)", () => {
    // useEffect that sets total from files.length + hasMore
    expect(src).toMatch(/setTotal\(files\.length\s*\+\s*\(hasMore\s*\?\s*1\s*:\s*0\)\)/);
  });

  it("5s poll uses refreshLoadedStatuses, not loadFiles(currentPage)", () => {
    // setInterval body must call the status-only refresh, not full reload
    expect(src).toMatch(/setInterval\([\s\S]*?refreshLoadedStatusesRef\.current\(\)/);
    expect(src).not.toMatch(/setInterval\([\s\S]*?loadFilesRef\.current\(currentPageRef/);
  });

  it("refreshLoadedStatuses does NOT touch nextCursor or hasMore", () => {
    // Extract the refreshLoadedStatuses callback body and assert it never
    // calls setNextCursor / setHasMore — only setFiles for the merge.
    const startIdx = src.indexOf("const refreshLoadedStatuses");
    expect(startIdx).toBeGreaterThan(-1);
    const endIdx = src.indexOf("const refreshLoadedStatusesRef", startIdx);
    expect(endIdx).toBeGreaterThan(startIdx);
    const body = src.slice(startIdx, endIdx);
    expect(body).not.toMatch(/setNextCursor\(/);
    expect(body).not.toMatch(/setHasMore\(/);
    // Must merge by id (Map keyed on String(id))
    expect(body).toMatch(/updatesById\.get\(String\(f\.id\)\)/);
    // Must prepend new rows that weren't already loaded
    expect(body).toMatch(/newRows\.length\s*>\s*0\s*\?\s*\[\.\.\.newRows,\s*\.\.\.merged\]\s*:\s*merged/);
  });

  it("refresh poll is skipped while in search state", () => {
    const startIdx = src.indexOf("const refreshLoadedStatuses");
    const endIdx = src.indexOf("const refreshLoadedStatusesRef", startIdx);
    const body = src.slice(startIdx, endIdx);
    // Early return guard: isSearching → return without fetching
    expect(body).toMatch(/if\s*\(isSearching\)\s*return/);
  });

  it("external knowledge-space-files refresh event resets to page 1", () => {
    // Structural change handler must call loadFiles(1), not the previous
    // currentPage — the accumulated tail is no longer trustworthy.
    expect(src).toMatch(/handleKnowledgeSpaceFilesRefresh[\s\S]{0,400}?loadFilesRef\.current\(1\)/);
  });
});

describe("SpaceDetail UI — F027 infinite-scroll guards", () => {
  const src = read("src/pages/knowledge/SpaceDetail/index.tsx");

  it("no longer imports PaginationBar", () => {
    expect(src).not.toMatch(/import\s*\{[^}]*PaginationBar[^}]*\}\s*from\s*["']\.\/PaginationBar["']/);
  });

  it("imports LoadMore from sibling file", () => {
    expect(src).toMatch(/import\s*\{\s*LoadMore\s*\}\s*from\s*["']\.\/LoadMore["']/);
  });

  it("declares hasMore prop on KnowledgeSpaceContentProps", () => {
    expect(src).toMatch(/hasMore:\s*boolean/);
  });

  it("renders the <LoadMore> sentinel through a shared bottom status", () => {
    expect(src).toMatch(/const\s+listBottomStatus[\s\S]{0,800}?<LoadMore/);
    expect(src).toMatch(/onLoad=\{onLoadMore\}/);
    expect(src).toMatch(/footer=\{listBottomStatus\}/);
  });

  it("LoadMore calls the KnowledgeSpaceContent onLoadMore prop", () => {
    expect(src).toMatch(/onLoad=\{onLoadMore\}/);
  });
});

describe("LoadMore component — F027 sentinel", () => {
  const src = read("src/pages/knowledge/SpaceDetail/LoadMore.tsx");

  it("uses IntersectionObserver rooted at nearest scrollable ancestor", () => {
    expect(src).toMatch(/findScrollableAncestor/);
    expect(src).toMatch(/new IntersectionObserver/);
    expect(src).toMatch(/overflowY\s*===\s*["']auto["']\s*\|\|\s*overflowY\s*===\s*["']scroll["']/);
  });

  it("keeps onLoad in a ref so observer always calls the latest closure", () => {
    expect(src).toMatch(/onLoadRef\.current\?\.\(\)/);
    expect(src).toMatch(/onLoadRef\.current\s*=\s*onLoad/);
  });

  it("disconnects observer on unmount", () => {
    expect(src).toMatch(/observer\.disconnect\(\)/);
  });
});
