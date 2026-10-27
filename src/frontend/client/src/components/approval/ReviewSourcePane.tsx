import { Outlined } from "bisheng-icons";
import { useEffect, useMemo, useState } from "react";
import {
  getSnapshotFileApi,
  type SnapshotEntry,
  type SnapshotFile,
} from "~/api/hostedAppReview";
import { extractApiErrorMessage } from "~/utils/apiStatusError";
import { cn } from "~/utils";
import type { LocalizeFn } from "./approvalPresentation";
import { ancestorPaths, buildReviewTree, pickInitialFile, type ReviewTreeNode } from "./reviewTree";

/**
 * Left file tree, right read-only code — the body of the review view (AC-25).
 *
 * Read-only is structural, not a `readOnly` attribute: the source is rendered
 * as text in a `<pre>`, there is no editor and no download. What comes back is
 * already masked by the backend, and a file the scanner would not read
 * (binary, over 1 MiB) is reported as such instead of being served.
 */

interface ReviewSourcePaneProps {
  appId: string;
  versionId: string;
  entries: SnapshotEntry[];
  /** The package holds more entries than the platform will list. */
  truncated: boolean;
  localize: LocalizeFn;
}

const REASON_KEY: Record<string, string> = {
  binary: "com_approval_review_not_previewable_binary",
  too_large: "com_approval_review_not_previewable_too_large",
};

function TreeRow({
  node,
  depth,
  selected,
  openDirs,
  onToggle,
  onSelect,
}: {
  node: ReviewTreeNode;
  depth: number;
  selected: string | null;
  openDirs: Set<string>;
  onToggle: (path: string) => void;
  onSelect: (path: string) => void;
}) {
  const isDir = node.type === "dir";
  const isOpen = isDir && openDirs.has(node.path);
  return (
    <>
      <button
        type="button"
        onClick={() => (isDir ? onToggle(node.path) : onSelect(node.path))}
        aria-expanded={isDir ? isOpen : undefined}
        aria-current={!isDir && node.path === selected}
        title={node.path}
        className={cn(
          "flex w-full items-center gap-1.5 py-1 pr-2 text-left text-[13px]",
          node.path === selected ? "bg-fill-2 text-text-primary" : "text-text-2 hover:bg-fill-1",
          !isDir && !node.previewable && "text-text-4",
        )}
        style={{ paddingLeft: `${depth * 12 + 8}px` }}
      >
        {isDir ? (
          <Outlined.Down
            className={cn("size-3 shrink-0 text-text-4 transition-transform", !isOpen && "-rotate-90")}
          />
        ) : (
          <span className="size-3 shrink-0" />
        )}
        <span className="min-w-0 flex-1 truncate">{node.name}</span>
      </button>
      {isOpen &&
        node.children.map((child) => (
          <TreeRow
            key={child.path}
            node={child}
            depth={depth + 1}
            selected={selected}
            openDirs={openDirs}
            onToggle={onToggle}
            onSelect={onSelect}
          />
        ))}
    </>
  );
}

export function ReviewSourcePane({ appId, versionId, entries, truncated, localize }: ReviewSourcePaneProps) {
  const tree = useMemo(() => buildReviewTree(entries), [entries]);
  const [selected, setSelected] = useState<string | null>(null);
  const [openDirs, setOpenDirs] = useState<Set<string>>(new Set());
  const [file, setFile] = useState<SnapshotFile | null>(null);
  const [loading, setLoading] = useState(false);
  // A box rather than a string for the same reason as in the view above: an
  // empty message must still read as "this failed", not as "nothing to show".
  const [failure, setFailure] = useState<{ message: string } | null>(null);

  // Land on the manifest (or the first readable file) and open the folders
  // that hold it, so the pane never opens on an empty right-hand side.
  useEffect(() => {
    const initial = pickInitialFile(entries);
    setSelected(initial);
    setOpenDirs(new Set(initial ? ancestorPaths(initial) : []));
  }, [entries]);

  useEffect(() => {
    if (!selected) {
      setFile(null);
      return;
    }
    const entry = entries.find((one) => one.path === selected);
    if (entry && entry.previewable === false) {
      // The tree already knows this one will not be served; asking anyway
      // would spend a round trip to be told the same thing.
      setFile(null);
      setFailure(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setFailure(null);
    getSnapshotFileApi(appId, versionId, selected)
      .then((data) => {
        if (!cancelled) setFile(data);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setFile(null);
        setFailure({ message: extractApiErrorMessage(error) });
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [appId, versionId, selected, entries]);

  const handleToggle = (path: string) =>
    setOpenDirs((current) => {
      const next = new Set(current);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });

  const selectedEntry = selected ? (entries.find((one) => one.path === selected) ?? null) : null;
  const notPreviewableKey =
    selectedEntry && selectedEntry.type === "file" && selectedEntry.previewable === false
      ? (REASON_KEY[selectedEntry.reason ?? ""] ?? "com_approval_review_not_previewable_generic")
      : null;

  if (entries.length === 0) {
    return <p className="text-[13px] text-text-3">{localize("com_approval_review_tree_empty")}</p>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 md:flex-row" data-testid="review-source-pane">
      <div className="flex max-h-56 shrink-0 flex-col overflow-y-auto rounded-lg border border-fill-2 md:max-h-none md:w-64">
        {tree.map((node) => (
          <TreeRow
            key={node.path}
            node={node}
            depth={0}
            selected={selected}
            openDirs={openDirs}
            onToggle={handleToggle}
            onSelect={setSelected}
          />
        ))}
        {truncated && (
          <p className="px-2 py-1.5 text-[12px] text-warning">
            {localize("com_approval_review_tree_truncated")}
          </p>
        )}
      </div>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-fill-2">
        {selected === null ? (
          <p className="p-4 text-[13px] text-text-3">{localize("com_approval_review_select_file")}</p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-fill-2 bg-fill-1 px-3 py-1.5 text-[12px] text-text-2">
              <span className="min-w-0 truncate font-mono" title={selected}>
                {selected}
              </span>
              {file && file.masked_secrets > 0 && (
                <span className="text-warning">
                  {localize("com_approval_review_masked_secrets", { count: file.masked_secrets })}
                </span>
              )}
            </div>
            {notPreviewableKey ? (
              <p className="p-4 text-[13px] text-text-3">{localize(notPreviewableKey)}</p>
            ) : failure ? (
              <p className="p-4 text-[13px] text-text-3">
                {failure.message || localize("com_approval_review_load_failed")}
              </p>
            ) : loading || !file ? (
              // `!file` as well as `loading`: the fetch starts in an effect, so
              // between picking a file and that effect running there is a frame
              // with neither a file nor a pending request — reading it as "not
              // previewable" would flash a wrong explanation on every click.
              <p className="p-4 text-[13px] text-text-3">{localize("com_approval_review_loading")}</p>
            ) : file.previewable ? (
              // `content` on a previewable file can legitimately be the empty
              // string — an empty file in the package. Branching on the verdict
              // rather than on the text keeps an empty file from being reported
              // as one the platform refuses to show.
              <pre className="scrollbar-os min-h-0 flex-1 overflow-auto p-3 font-mono text-[12px] leading-5 text-text-primary">
                {file.content ?? ""}
              </pre>
            ) : (
              <p className="p-4 text-[13px] text-text-3">
                {localize(
                  REASON_KEY[file.reason ?? ""] ?? "com_approval_review_not_previewable_generic",
                )}
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
