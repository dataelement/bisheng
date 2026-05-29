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

const repoRoot = join(__dirname, "..", "..", "..", "..");

function read(rel: string): string {
  return readFileSync(join(repoRoot, rel), "utf8");
}

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

  it("renders <LoadMore> sentinel guarded by hasMore in both card and list views", () => {
    // Two occurrences — one in card-grid container, one in list-table container.
    const matches = src.match(/\{hasMore\s*&&\s*\(\s*<LoadMore/g) || [];
    expect(matches.length).toBeGreaterThanOrEqual(2);
  });

  it("LoadMore triggers onPageChange(currentPage + 1)", () => {
    expect(src).toMatch(/onLoad=\{\(\)\s*=>\s*onPageChange\(currentPage\s*\+\s*1\)\}/);
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
