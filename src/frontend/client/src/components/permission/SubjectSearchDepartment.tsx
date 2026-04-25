import { Checkbox } from "~/components/ui/Checkbox";
import { Input } from "~/components/ui/Input";
import { getDepartmentTree, getKnowledgeSpaceGrantDepartments } from "~/api/permission";
import type { ResourceType, SelectedSubject } from "~/api/permission";
import { ChevronDown, ChevronRight, Building2, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useLocalize } from "~/hooks";

interface DepartmentNode {
  id: number;
  dept_id: string;
  name: string;
  parent_id: number | null;
  member_count?: number;
  children?: DepartmentNode[];
}

interface SubjectSearchDepartmentProps {
  value: SelectedSubject[];
  onChange: (v: SelectedSubject[]) => void;
  resourceType?: ResourceType;
  resourceId?: string;
  includeChildren: boolean;
  onIncludeChildrenChange: (v: boolean) => void;
}

export function SubjectSearchDepartment({
  value,
  onChange,
  resourceType,
  resourceId,
  includeChildren,
  onIncludeChildrenChange,
}: SubjectSearchDepartmentProps) {
  const localize = useLocalize();
  const [tree, setTree] = useState<DepartmentNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [keyword, setKeyword] = useState("");
  const [expanded, setExpanded] = useState<Set<number>>(new Set());

  useEffect(() => {
    const controller = new AbortController();
    const request =
      resourceType === "knowledge_space" && resourceId
        ? getKnowledgeSpaceGrantDepartments(resourceId, { signal: controller.signal })
        : getDepartmentTree({ signal: controller.signal });

    setLoading(true);
    request
      .then((res) => {
        if (!controller.signal.aborted && res) setTree(res);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });

    return () => controller.abort();
  }, [resourceId, resourceType]);

  const selectedIds = new Set(value.map((s) => s.id));

  const toggle = (node: DepartmentNode) => {
    if (selectedIds.has(node.id)) {
      onChange(value.filter((s) => s.id !== node.id));
    } else {
      onChange([
        ...value,
        { type: "department", id: node.id, name: node.name, include_children: includeChildren },
      ]);
    }
  };

  const toggleExpand = (id: number) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const matchesKeyword = useCallback(
    (node: DepartmentNode): boolean => {
      if (!keyword) return true;
      const lower = keyword.toLowerCase();
      if (node.name.toLowerCase().includes(lower)) return true;
      return (node.children || []).some(matchesKeyword);
    },
    [keyword]
  );

  useEffect(() => {
    if (!keyword) return;
    const ids = new Set<number>();
    const collect = (nodes: DepartmentNode[]) => {
      for (const n of nodes) {
        if (matchesKeyword(n)) {
          ids.add(n.id);
          if (n.children) collect(n.children);
        }
      }
    };
    collect(tree);
    setExpanded(ids);
  }, [tree, keyword, matchesKeyword]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <div className="relative shrink-0">
        <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
        <Input
          placeholder={localize("com_permission.search_department")}
          value={keyword}
          onChange={(e) => setKeyword(e.target.value)}
          className="h-8 pl-8"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto rounded-md border">
        {loading && (
          <div className="py-4 text-center text-sm text-gray-500">{localize("com_ui_loading")}</div>
        )}
        {!loading && tree.length === 0 && (
          <div className="py-4 text-center text-sm text-gray-500">
            {localize("com_permission.empty_departments")}
          </div>
        )}
        {!loading &&
          tree.map((node) => (
            <TreeNode
              key={node.id}
              node={node}
              depth={0}
              expanded={expanded}
              selectedIds={selectedIds}
              matchesKeyword={matchesKeyword}
              onToggle={toggle}
              onExpand={toggleExpand}
            />
          ))}
      </div>
    </div>
  );
}

function TreeNode({
  node, depth, expanded, selectedIds, matchesKeyword, onToggle, onExpand,
}: {
  node: DepartmentNode;
  depth: number;
  expanded: Set<number>;
  selectedIds: Set<number>;
  matchesKeyword: (n: DepartmentNode) => boolean;
  onToggle: (n: DepartmentNode) => void;
  onExpand: (id: number) => void;
}) {
  if (!matchesKeyword(node)) return null;
  const hasChildren = node.children && node.children.length > 0;
  const isExpanded = expanded.has(node.id);

  return (
    <>
      <div
        className="flex cursor-pointer items-center gap-1 px-2 py-1.5 hover:bg-gray-50"
        style={{ paddingLeft: `${depth * 16 + 8}px` }}
        onClick={() => onToggle(node)}
      >
        {hasChildren ? (
          <button
            className="rounded p-0.5 hover:bg-gray-200"
            onClick={(e) => { e.stopPropagation(); onExpand(node.id); }}
          >
            {isExpanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
          </button>
        ) : (
          <span className="w-5" />
        )}
        <Checkbox
          checked={selectedIds.has(node.id)}
          onClick={(e) => e.stopPropagation()}
          onCheckedChange={() => onToggle(node)}
        />
        <Building2 className="h-4 w-4 text-gray-400" />
        <span className="truncate text-sm">{node.name}</span>
        {node.member_count != null && (
          <span className="ml-1 text-xs text-gray-400">({node.member_count})</span>
        )}
      </div>
      {hasChildren && isExpanded && node.children!.map((child) => (
        <TreeNode
          key={child.id}
          node={child}
          depth={depth + 1}
          expanded={expanded}
          selectedIds={selectedIds}
          matchesKeyword={matchesKeyword}
          onToggle={onToggle}
          onExpand={onExpand}
        />
      ))}
    </>
  );
}
