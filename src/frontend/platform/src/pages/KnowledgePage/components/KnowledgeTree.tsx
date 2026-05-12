import { ChevronDown, ChevronRight, Folder } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { KnowledgeNode, listKnowledgeChildren } from "@/controllers/API";

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

    const handleExpand = useCallback(
        async (e: React.MouseEvent) => {
            e.stopPropagation();
            if (children === null) {
                setLoading(true);
                try {
                    const resp = await listKnowledgeChildren({
                        knowledge_id: knowledgeId,
                        parent_id: node.id,
                        file_type: 0,
                    });
                    setChildren(resp.items);
                } finally {
                    setLoading(false);
                }
            }
            setExpanded((v) => !v);
        },
        [knowledgeId, node.id, children]
    );

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
                    {expanded ? (
                        <ChevronDown className="w-3 h-3" />
                    ) : (
                        <ChevronRight className="w-3 h-3" />
                    )}
                </button>
                <Folder className="w-4 h-4 text-blue-500" />
                <span
                    className="flex-1 text-sm truncate"
                    onClick={() => onSelectFolder({ id: node.id, name: node.file_name })}
                >
                    {node.file_name}
                </span>
            </div>
            {expanded && loading && (
                <div
                    style={{ paddingLeft: (depth + 1) * INDENT_PX + 4 }}
                    className="text-xs text-gray-400 py-1"
                >
                    Loading…
                </div>
            )}
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
        </div>
    );
}

/**
 * Left-sidebar directory tree for a knowledge space.
 * Only shows DIR nodes (file_type=0); files are shown in the right panel.
 * Uses optimistic expand arrows — lazy loads children on first expand.
 */
export function KnowledgeTree({ knowledgeId, onSelectFolder }: KnowledgeTreeProps) {
    const [roots, setRoots] = useState<KnowledgeNode[]>([]);

    useEffect(() => {
        listKnowledgeChildren({
            knowledge_id: knowledgeId,
            parent_id: null,
            file_type: 0,
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
