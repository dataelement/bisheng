import { useLocalize } from "~/hooks";
import {
  ChevronDown,
  ChevronRight,
  FolderClosedIcon,
  Loader2,
  Plus,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { getFullWidthLength } from "~/utils";
import { ChannelNotebookOneIcon } from "~/components/icons/channels";
import type { KnowledgeNode } from "./AddToKnowledgeModal";

/** Find node in tree and execute operation */
export function mapTree(
  nodes: KnowledgeNode[],
  predicate: (n: KnowledgeNode) => boolean,
  transform: (n: KnowledgeNode) => KnowledgeNode,
): KnowledgeNode[] {
  return nodes.map((n) => {
    if (predicate(n)) return transform(n);
    return {
      ...n,
      children: n.children ? mapTree(n.children, predicate, transform) : [],
    };
  });
}

/** Recursively filter matching nodes, preserving ancestor paths */
export function filterTree(
  nodes: KnowledgeNode[],
  keyword: string,
): KnowledgeNode[] {
  const kw = keyword.toLowerCase();
  return nodes.reduce<KnowledgeNode[]>((acc, node) => {
    const filteredChildren = filterTree(node.children ?? [], keyword);
    const matches = node.name.toLowerCase().includes(kw);
    if (matches || filteredChildren.length > 0) {
      acc.push({ ...node, children: filteredChildren });
    }
    return acc;
  }, []);
}

/** Find a node by id recursively */
export function findNode(
  nodes: KnowledgeNode[],
  id: string,
): KnowledgeNode | undefined {
  for (const n of nodes) {
    if (n.id === id) return n;
    if (n.children) {
      const found = findNode(n.children, id);
      if (found) return found;
    }
  }
  return undefined;
}

// ─── Inline Editing Input ─────────────────────────────────────────────

interface InlineEditProps {
  defaultValue: string;
  onSave: (name: string) => void;
  onCancel: () => void;
  onValidate: (name: string) => boolean;
}

function InlineEdit({
  defaultValue,
  onSave,
  onCancel,
  onValidate,
}: InlineEditProps) {
  const ref = useRef<HTMLInputElement>(null);
  const [value, setValue] = useState(defaultValue);

  useEffect(() => {
    if (ref.current) {
      ref.current.focus();
      ref.current.select();
    }
  }, []);

  const commit = () => {
    const trimmed = value.trim();
    if (!trimmed) {
      onCancel();
      return;
    }
    if (getFullWidthLength(trimmed) > 50) {
      onCancel();
      return;
    }
    if (!onValidate(trimmed)) {
      onCancel();
      return;
    }
    onSave(trimmed);
  };

  return (
    <input
      ref={ref}
      value={value}
      onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          commit();
        }
        if (e.key === "Escape") {
          e.preventDefault();
          onCancel();
        }
      }}
      onBlur={commit}
      maxLength={50}
      className="flex-1 min-w-0 border border-primary rounded px-1.5 py-0 text-sm outline-none bg-white text-primary"
      onClick={(e) => e.stopPropagation()}
    />
  );
}

// ─── Tree Node Row ─────────────────────────────────────────────────────

interface TreeNodeProps {
  node: KnowledgeNode;
  nodes: KnowledgeNode[];
  selectedId: string | null;
  expandedIds: Set<string>;
  editingId: string | null;
  onSelect: (id: string) => void;
  onToggle: (id: string) => void;
  onAddFolder: (parentId: string, parentLevel: number, spaceId: string) => void;
  onSaveEdit: (id: string, name: string) => void;
  onCancelEdit: () => void;
  searchMode: boolean;
}

export function TreeNode({
  node,
  nodes,
  selectedId,
  expandedIds,
  editingId,
  onSelect,
  onToggle,
  onAddFolder,
  onSaveEdit,
  onCancelEdit,
  searchMode,
}: TreeNodeProps) {
  const localize = useLocalize();
  const isExpanded = searchMode || expandedIds.has(node.id);
  const isSelected = selectedId === node.id;
  const isEditing = editingId === node.id;
  // Show expand arrow for spaces (always expandable) or folders with known children
  const hasOrMayHaveChildren =
    node.type === "space" ||
    (node.children?.length ?? 0) > 0 ||
    !node.childrenLoaded;
  const indent = (node.level - 1) * 16;

  const { showToast } = useToastContext();

  return (
    <div className="w-full min-w-0 max-w-full space-y-1">
      <div
        className={`group relative flex w-full min-w-0 max-w-full box-border items-center gap-1.5 py-1 px-2 rounded-md cursor-pointer text-sm select-none overflow-hidden
                    ${isSelected ? "bg-blue-50 text-primary" : "hover:bg-gray-50 coarse-pointer:hover:bg-transparent"}`}
        style={{
          paddingLeft: `${indent + 8}px`,
          transitionProperty: "background-color",
          transitionDuration: "350ms",
          transitionTimingFunction: "ease-in-out",
        }}
        onClick={() => onSelect(node.id)}
      >
        {/* Expand toggle */}
        <span
          className="shrink-0 size-4 flex items-center justify-center text-text-3"
          onClick={(e) => {
            e.stopPropagation();
            onToggle(node.id);
          }}
        >
          {node.childrenLoading ? (
            <Loader2 className="size-3 animate-spin" />
          ) : hasOrMayHaveChildren ? (
            isExpanded ? (
              <ChevronDown className="size-3.5" />
            ) : (
              <ChevronRight className="size-3.5" />
            )
          ) : (
            <span className="size-3.5" />
          )}
        </span>

        {/* Icon */}
        {node.type === "space" ? (
          <ChannelNotebookOneIcon className="size-[14px] shrink-0 object-contain opacity-90" />
        ) : (
          <FolderClosedIcon
            className={`shrink-0 size-3.5 ${isSelected ? "text-primary" : "text-text-2"}`}
          />
        )}

        {/* Name / Inline edit */}
        {isEditing ? (
          <InlineEdit
            defaultValue={node.name}
            onValidate={(name) => {
              if (nodes.some((n) => n.id !== node.id && n.name === name)) {
                showToast({
                  message: localize("com_subscription.folder_name_duplicate"),
                  severity: NotificationSeverity.WARNING,
                });
                return false;
              }
              return true;
            }}
            onSave={(name) => onSaveEdit(node.id, name)}
            onCancel={onCancelEdit}
          />
        ) : (
          <span className="min-w-0 flex-1 overflow-hidden pr-0 transition-[padding-right] duration-150 fine-pointer:group-hover:pr-8 coarse-pointer:pr-8">
            <span className="block truncate" title={node.name}>
              {node.name}
            </span>
          </span>
        )}

        {/* Add folder button (hover) */}
        {!isEditing && (
          <button
            type="button"
            className="absolute right-2 top-1/2 z-[1] flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded text-text-3 opacity-0 pointer-events-none transition-colors duration-150 fine-pointer:group-hover:pointer-events-auto fine-pointer:group-hover:opacity-100 hover:text-primary coarse-pointer:pointer-events-auto coarse-pointer:opacity-100"
            title={localize("com_subscription.new_subfolder")}
            onClick={(e) => {
              e.stopPropagation();
              onAddFolder(node.id, node.level, node.spaceId);
            }}
          >
            <Plus className="shrink-0 w-4 h-4 text-primary" strokeWidth={2} />
          </button>
        )}
      </div>

      {/* Children */}
      {isExpanded && node.children && node.children.length > 0 && (
        <div className="w-full min-w-0 max-w-full space-y-1">
          {node.children.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              nodes={node.children || []}
              selectedId={selectedId}
              expandedIds={expandedIds}
              editingId={editingId}
              onSelect={onSelect}
              onToggle={onToggle}
              onAddFolder={onAddFolder}
              onSaveEdit={onSaveEdit}
              onCancelEdit={onCancelEdit}
              searchMode={searchMode}
            />
          ))}
        </div>
      )}
    </div>
  );
}
