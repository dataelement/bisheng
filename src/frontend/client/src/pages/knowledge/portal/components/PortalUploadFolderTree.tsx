import { ChevronDown, ChevronRight, Folder } from "lucide-react";
import s from "../PortalKnowledgeWorkbench.module.css";

export interface FolderTreeNode {
    id: string;
    name: string;
    children: FolderTreeNode[];
    expanded: boolean;
    loaded: boolean;
    loading: boolean;
}

export interface PortalUploadFolderTreeNodeProps {
    node: FolderTreeNode;
    depth: number;
    recordName: string;
    targetFolderId: string | null;
    onToggle: (node: FolderTreeNode) => void;
    onSelect: (folderId: string, folderName: string) => void;
}

export function createFolderTreeNode(item: any): FolderTreeNode {
    return {
        id: String(item.id),
        name: String(item.file_name ?? item.name ?? ""),
        children: [],
        expanded: false,
        loaded: false,
        loading: false,
    };
}

export function updateFolderTreeNode(
    nodes: FolderTreeNode[],
    nodeId: string,
    updater: (node: FolderTreeNode) => FolderTreeNode,
): FolderTreeNode[] {
    return nodes.map((node) => {
        if (node.id === nodeId) return updater(node);
        if (!node.children.length) return node;
        return { ...node, children: updateFolderTreeNode(node.children, nodeId, updater) };
    });
}

export function PortalUploadFolderTreeNode({
    node,
    depth,
    recordName,
    targetFolderId,
    onToggle,
    onSelect,
}: PortalUploadFolderTreeNodeProps) {
    return (
        <div key={node.id}>
            <div className={s.uploadRecordFolderRow} style={{ paddingLeft: `${8 + depth * 16}px` }}>
                <button
                    type="button"
                    className={s.uploadRecordFolderExpandButton}
                    aria-label={`${node.expanded ? "收起" : "展开"}${recordName}目标目录${node.name}`}
                    onClick={() => onToggle(node)}
                >
                    {node.expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
                </button>
                <button
                    type="button"
                    className={`${s.uploadRecordFolderSelectButton} ${targetFolderId === node.id ? s.uploadRecordFolderSelectButtonActive : ""}`}
                    aria-label={`选择${recordName}目标目录${node.name}`}
                    onClick={() => onSelect(node.id, node.name)}
                >
                    <Folder size={14} />
                    <span>{node.name}</span>
                </button>
            </div>
            {node.expanded && node.loading ? (
                <div className={s.uploadRecordFolderLoading} style={{ paddingLeft: `${30 + (depth + 1) * 16}px` }}>
                    加载中...
                </div>
            ) : null}
            {node.expanded ? node.children.map((child) => (
                <PortalUploadFolderTreeNode
                    key={child.id}
                    node={child}
                    depth={depth + 1}
                    recordName={recordName}
                    targetFolderId={targetFolderId}
                    onToggle={onToggle}
                    onSelect={onSelect}
                />
            )) : null}
        </div>
    );
}
