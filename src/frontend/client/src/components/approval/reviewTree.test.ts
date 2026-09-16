import type { SnapshotEntry } from "~/api/hostedAppReview";
import { ancestorPaths, buildReviewTree, pickInitialFile } from "./reviewTree";

/** What `GET …/snapshot/tree` sends: flat, path-sorted, directories derived. */
function entries(): SnapshotEntry[] {
  return [
    { path: "README.md", name: "README.md", type: "file", size: 12, previewable: true, reason: null },
    { path: "bisheng-app.yaml", name: "bisheng-app.yaml", type: "file", size: 40, previewable: true, reason: null },
    { path: "src", name: "src", type: "dir", size: null },
    { path: "src/app", name: "app", type: "dir", size: null },
    { path: "src/app/main.py", name: "main.py", type: "file", size: 90, previewable: true, reason: null },
    { path: "src/logo.png", name: "logo.png", type: "file", size: 9000, previewable: false, reason: "binary" },
  ];
}

describe("buildReviewTree", () => {
  it("nests every entry under its directory", () => {
    const tree = buildReviewTree(entries());

    // Directories first, then files by `localeCompare` — which is
    // case-insensitive, so `bisheng-app.yaml` sorts above `README.md`.
    expect(tree.map((node) => node.path)).toEqual(["src", "bisheng-app.yaml", "README.md"]);
    const src = tree[0];
    expect(src.children.map((node) => node.path)).toEqual(["src/app", "src/logo.png"]);
    expect(src.children[0].children.map((node) => node.path)).toEqual(["src/app/main.py"]);
  });

  it("puts directories before files and sorts each group by name", () => {
    const tree = buildReviewTree([
      { path: "z.py", name: "z.py", type: "file", size: 1, previewable: true, reason: null },
      { path: "a.py", name: "a.py", type: "file", size: 1, previewable: true, reason: null },
      { path: "lib", name: "lib", type: "dir", size: null },
    ]);
    expect(tree.map((node) => node.name)).toEqual(["lib", "a.py", "z.py"]);
  });

  it("carries the previewable verdict through so the tree can grey a file out", () => {
    const tree = buildReviewTree(entries());
    const logo = tree[0].children.find((node) => node.name === "logo.png");
    expect(logo).toMatchObject({ previewable: false, reason: "binary" });
  });

  it("keeps a file whose directory was never listed at the root rather than dropping it", () => {
    // An archive that omits directory members is the normal case; the backend
    // derives them, but the fold must not depend on that having happened.
    const tree = buildReviewTree([
      { path: "deep/nested/file.py", name: "file.py", type: "file", size: 1, previewable: true, reason: null },
    ]);
    expect(tree).toHaveLength(1);
    expect(tree[0].path).toBe("deep/nested/file.py");
  });
});

describe("ancestorPaths", () => {
  it("names every directory that has to be open for a path to be visible", () => {
    expect(ancestorPaths("src/app/main.py")).toEqual(["src", "src/app"]);
    expect(ancestorPaths("main.py")).toEqual([]);
  });
});

describe("pickInitialFile", () => {
  it("opens on the manifest, which is the file every reviewer reads first", () => {
    expect(pickInitialFile(entries())).toBe("bisheng-app.yaml");
  });

  it("falls back to the first readable file and skips the ones that cannot be shown", () => {
    const withoutManifest = entries().filter((entry) => entry.path !== "bisheng-app.yaml");
    expect(pickInitialFile(withoutManifest)).toBe("README.md");
    expect(
      pickInitialFile([
        { path: "logo.png", name: "logo.png", type: "file", size: 9, previewable: false, reason: "binary" },
      ]),
    ).toBeNull();
  });

  it("returns null for a package with no files at all", () => {
    expect(pickInitialFile([])).toBeNull();
  });
});
