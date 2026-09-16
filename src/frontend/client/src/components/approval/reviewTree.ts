import type { SnapshotEntry } from "~/api/hostedAppReview";

/**
 * Folding the backend's flat entry list into the tree the review view draws.
 *
 * The listing is flat and path-sorted by design (an archive that omits
 * directory members still yields a complete tree, because the backend derives
 * directories from file paths). Turning it back into a tree is pure string
 * work, so it lives apart from the component and is tested on its own.
 */

export interface ReviewTreeNode {
  path: string;
  name: string;
  type: "file" | "dir";
  size: number | null;
  previewable: boolean;
  reason: string | null;
  children: ReviewTreeNode[];
}

function parentPath(path: string): string {
  const cut = path.lastIndexOf("/");
  return cut === -1 ? "" : path.slice(0, cut);
}

/**
 * Directories first, then files, each alphabetically — the order every file
 * browser uses, and the one that keeps a deep `src/` from being buried under
 * loose root files.
 */
function compareNodes(a: ReviewTreeNode, b: ReviewTreeNode): number {
  if (a.type !== b.type) return a.type === "dir" ? -1 : 1;
  return a.name.localeCompare(b.name);
}

export function buildReviewTree(entries: SnapshotEntry[]): ReviewTreeNode[] {
  const nodes = new Map<string, ReviewTreeNode>();
  const roots: ReviewTreeNode[] = [];

  // Shallowest first so a parent always exists by the time its child arrives;
  // the backend sorts by path, which is not the same thing ("a/b" precedes
  // "a.txt" but "a" precedes both).
  const ordered = [...entries].sort(
    (a, b) => a.path.split("/").length - b.path.split("/").length || a.path.localeCompare(b.path),
  );

  for (const entry of ordered) {
    if (!entry.path || nodes.has(entry.path)) continue;
    const node: ReviewTreeNode = {
      path: entry.path,
      name: entry.name || entry.path.split("/").pop() || entry.path,
      type: entry.type,
      size: entry.size ?? null,
      previewable: entry.type === "file" ? entry.previewable !== false : false,
      reason: entry.reason ?? null,
      children: [],
    };
    nodes.set(node.path, node);
    const parent = nodes.get(parentPath(entry.path));
    if (parent && parent.type === "dir") parent.children.push(node);
    else roots.push(node);
  }

  const sortDeep = (list: ReviewTreeNode[]) => {
    list.sort(compareNodes);
    for (const node of list) sortDeep(node.children);
  };
  sortDeep(roots);
  return roots;
}

/** Every directory on the way to `path` — what has to be open for it to be visible. */
export function ancestorPaths(path: string): string[] {
  const parts = path.split("/").filter(Boolean);
  return parts.slice(0, -1).map((_part, index) => parts.slice(0, index + 1).join("/"));
}

/**
 * Which file to open when the view mounts: the manifest if the package has
 * one (it is the one file every reviewer reads first), else the first
 * previewable file in tree order, else nothing.
 */
export function pickInitialFile(entries: SnapshotEntry[]): string | null {
  const files = entries.filter((entry) => entry.type === "file" && entry.previewable !== false);
  const manifest = files.find((entry) => entry.path === "bisheng-app.yaml");
  return manifest?.path ?? files[0]?.path ?? null;
}
