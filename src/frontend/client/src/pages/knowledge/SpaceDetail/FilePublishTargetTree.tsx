import { useMemo, useState } from "react";
import { ChevronRight, Folder, FolderOpen, Library } from "lucide-react";
import type { ShougangFilePublishTargetSpace } from "~/api/approval";
import { listKnowledgeFolders } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";

type PublishTargetLevel = "public" | "department" | "team" | "personal";

type TargetFolderNode = {
    id: string;
    name: string;
    children: TargetFolderNode[];
    expanded: boolean;
    loading: boolean;
    loaded: boolean;
};

type SpaceFolderTreeState = {
    expanded: boolean;
    loading: boolean;
    loaded: boolean;
    folders: TargetFolderNode[];
};

interface FilePublishTargetTreeProps {
    loading: boolean;
    targetSpaces: ShougangFilePublishTargetSpace[];
    targetSpaceId: string;
    targetFolderId: string | null;
    onSelectRoot: (spaceId: string | number) => void;
    onSelectFolder: (spaceId: string | number, folderId: string | number) => void;
}

const TARGET_LEVEL_LABELS: Record<PublishTargetLevel, string> = {
    public: "公共知识库",
    department: "部门知识库",
    team: "团队知识库",
    personal: "个人知识库",
};

const TARGET_LEVEL_ORDER: PublishTargetLevel[] = ["public", "department", "team", "personal"];

function getTargetSpaceLevel(space: ShougangFilePublishTargetSpace): PublishTargetLevel {
    return String((space as any).space_level ?? (space as any).spaceLevel ?? "personal") as PublishTargetLevel;
}

function mapFolderNode(item: any): TargetFolderNode {
    return {
        id: String(item.id),
        name: String(item.file_name ?? item.name ?? ""),
        children: [],
        expanded: false,
        loading: false,
        loaded: false,
    };
}

function updateFolderNode(
    nodes: TargetFolderNode[],
    folderId: string,
    updater: (node: TargetFolderNode) => TargetFolderNode,
): TargetFolderNode[] {
    return nodes.map((node) => {
        if (node.id === folderId) return updater(node);
        return { ...node, children: updateFolderNode(node.children, folderId, updater) };
    });
}

export function FilePublishTargetTree({
    loading,
    targetSpaces,
    targetSpaceId,
    targetFolderId,
    onSelectRoot,
    onSelectFolder,
}: FilePublishTargetTreeProps) {
    const { showToast } = useToastContext();
    const [targetFolderTrees, setTargetFolderTrees] = useState<Record<string, SpaceFolderTreeState>>({});

    const targetSpaceGroups = useMemo(() => {
        const grouped = new Map<PublishTargetLevel, ShougangFilePublishTargetSpace[]>();
        targetSpaces.forEach((space) => {
            const level = getTargetSpaceLevel(space);
            if (!grouped.has(level)) grouped.set(level, []);
            grouped.get(level)?.push(space);
        });
        return TARGET_LEVEL_ORDER
            .map((level) => ({ level, spaces: grouped.get(level) || [] }))
            .filter((group) => group.spaces.length > 0);
    }, [targetSpaces]);

    const handleToggleSpaceFolders = async (spaceId: string | number) => {
        const key = String(spaceId);
        const current = targetFolderTrees[key];
        setTargetFolderTrees((prev) => ({
            ...prev,
            [key]: {
                expanded: !(prev[key]?.expanded ?? false),
                loading: prev[key]?.loading ?? false,
                loaded: prev[key]?.loaded ?? false,
                folders: prev[key]?.folders ?? [],
            },
        }));
        if (current?.loaded || current?.loading) return;
        setTargetFolderTrees((prev) => ({
            ...prev,
            [key]: {
                expanded: true,
                loading: true,
                loaded: false,
                folders: prev[key]?.folders ?? [],
            },
        }));
        try {
            const res = await listKnowledgeFolders({ space_id: spaceId, parent_id: null });
            setTargetFolderTrees((prev) => ({
                ...prev,
                [key]: {
                    expanded: prev[key]?.expanded ?? true,
                    loading: false,
                    loaded: true,
                    folders: (res.items || []).map(mapFolderNode),
                },
            }));
        } catch {
            setTargetFolderTrees((prev) => ({
                ...prev,
                [key]: {
                    expanded: prev[key]?.expanded ?? true,
                    loading: false,
                    loaded: false,
                    folders: prev[key]?.folders ?? [],
                },
            }));
            showToast({ message: "加载目标目录失败", severity: NotificationSeverity.ERROR });
        }
    };

    const handleToggleFolder = async (spaceId: string | number, folderId: string | number) => {
        const spaceKey = String(spaceId);
        const folderKey = String(folderId);
        const findFolder = (nodes: TargetFolderNode[]): TargetFolderNode | undefined => {
            for (const node of nodes) {
                if (node.id === folderKey) return node;
                const child = findFolder(node.children);
                if (child) return child;
            }
            return undefined;
        };
        const current = findFolder(targetFolderTrees[spaceKey]?.folders || []);
        setTargetFolderTrees((prev) => ({
            ...prev,
            [spaceKey]: {
                ...(prev[spaceKey] || { expanded: true, loading: false, loaded: true, folders: [] }),
                folders: updateFolderNode(prev[spaceKey]?.folders || [], folderKey, (node) => ({
                    ...node,
                    expanded: !node.expanded,
                })),
            },
        }));
        if (current?.loaded || current?.loading) return;
        setTargetFolderTrees((prev) => ({
            ...prev,
            [spaceKey]: {
                ...(prev[spaceKey] || { expanded: true, loading: false, loaded: true, folders: [] }),
                folders: updateFolderNode(prev[spaceKey]?.folders || [], folderKey, (node) => ({
                    ...node,
                    expanded: true,
                    loading: true,
                })),
            },
        }));
        try {
            const res = await listKnowledgeFolders({ space_id: spaceId, parent_id: folderId });
            setTargetFolderTrees((prev) => ({
                ...prev,
                [spaceKey]: {
                    ...(prev[spaceKey] || { expanded: true, loading: false, loaded: true, folders: [] }),
                    folders: updateFolderNode(prev[spaceKey]?.folders || [], folderKey, (node) => ({
                        ...node,
                        loading: false,
                        loaded: true,
                        children: (res.items || []).map(mapFolderNode),
                    })),
                },
            }));
        } catch {
            setTargetFolderTrees((prev) => ({
                ...prev,
                [spaceKey]: {
                    ...(prev[spaceKey] || { expanded: true, loading: false, loaded: true, folders: [] }),
                    folders: updateFolderNode(prev[spaceKey]?.folders || [], folderKey, (node) => ({
                        ...node,
                        loading: false,
                        loaded: false,
                    })),
                },
            }));
            showToast({ message: "加载目标目录失败", severity: NotificationSeverity.ERROR });
        }
    };

    const renderFolderNodes = (space: ShougangFilePublishTargetSpace, nodes: TargetFolderNode[], depth = 0) => (
        nodes.map((folder) => {
            const selected = targetSpaceId === String(space.id) && targetFolderId === folder.id;
            return (
                <div key={folder.id}>
                    <div className="flex items-center gap-1" style={{ paddingLeft: depth * 16 }}>
                        <button
                            type="button"
                            aria-label={`展开${folder.name}目录`}
                            className="flex h-7 w-7 items-center justify-center rounded text-[#4e5969] hover:bg-[#f2f3f5]"
                            onClick={() => void handleToggleFolder(space.id, folder.id)}
                        >
                            <ChevronRight
                                size={14}
                                className={folder.expanded ? "rotate-90 transition-transform" : "transition-transform"}
                            />
                        </button>
                        <button
                            type="button"
                            aria-label={`选择目录${folder.name}`}
                            className={`flex h-8 min-w-0 flex-1 items-center gap-2 rounded px-2 text-left text-sm ${
                                selected ? "bg-[#e8f3ff] text-[#165dff]" : "text-[#1d2129] hover:bg-[#f7f8fa]"
                            }`}
                            onClick={() => onSelectFolder(space.id, folder.id)}
                        >
                            {folder.expanded ? <FolderOpen size={14} /> : <Folder size={14} />}
                            <span className="truncate">{folder.name}</span>
                        </button>
                    </div>
                    {folder.loading ? (
                        <div className="py-1 text-xs text-[#86909c]" style={{ paddingLeft: depth * 16 + 40 }}>
                            目录加载中...
                        </div>
                    ) : null}
                    {folder.expanded && folder.children.length > 0
                        ? renderFolderNodes(space, folder.children, depth + 1)
                        : null}
                </div>
            );
        })
    );

    if (loading) {
        return <div className="px-2 py-6 text-center text-sm text-[#86909c]">加载中...</div>;
    }
    if (targetSpaceGroups.length === 0) {
        return <div className="px-2 py-6 text-center text-sm text-[#86909c]">暂无可发布目标</div>;
    }

    return (
        <div className="space-y-3">
            {targetSpaceGroups.map((group) => (
                <div key={group.level} className="space-y-1">
                    <div className="px-1 text-xs font-medium text-[#86909c]">
                        {TARGET_LEVEL_LABELS[group.level]}
                    </div>
                    {group.spaces.map((space) => {
                        const spaceId = String(space.id);
                        const tree = targetFolderTrees[spaceId];
                        const rootSelected = targetSpaceId === spaceId && targetFolderId === null;
                        return (
                            <div key={spaceId} className="space-y-1">
                                <div className="flex items-center gap-1">
                                    <button
                                        type="button"
                                        aria-label={`展开${space.name}目录`}
                                        className="flex h-7 w-7 items-center justify-center rounded text-[#4e5969] hover:bg-[#f2f3f5]"
                                        onClick={() => void handleToggleSpaceFolders(space.id)}
                                    >
                                        <ChevronRight
                                            size={14}
                                            className={tree?.expanded ? "rotate-90 transition-transform" : "transition-transform"}
                                        />
                                    </button>
                                    <button
                                        type="button"
                                        aria-label={`选择${space.name}根目录`}
                                        className={`flex h-8 min-w-0 flex-1 items-center gap-2 rounded px-2 text-left text-sm ${
                                            rootSelected ? "bg-[#e8f3ff] text-[#165dff]" : "text-[#1d2129] hover:bg-[#f7f8fa]"
                                        }`}
                                        onClick={() => onSelectRoot(space.id)}
                                    >
                                        <Library size={14} />
                                        <span className="min-w-0 flex-1 truncate">{space.name}</span>
                                        <span className="shrink-0 text-xs text-[#86909c]">根目录</span>
                                    </button>
                                </div>
                                {tree?.loading ? (
                                    <div className="py-1 pl-10 text-xs text-[#86909c]">目录加载中...</div>
                                ) : null}
                                {tree?.expanded && tree.folders.length > 0
                                    ? renderFolderNodes(space, tree.folders, 1)
                                    : null}
                                {tree?.expanded && tree.loaded && tree.folders.length === 0 ? (
                                    <div className="py-1 pl-10 text-xs text-[#86909c]">暂无子目录</div>
                                ) : null}
                            </div>
                        );
                    })}
                </div>
            ))}
        </div>
    );
}
