import { useState } from "react";
import { Plus, Search, ChevronDown, ChevronRight, Pin, MoreVertical, Folder } from "lucide-react";
import { KnowledgeSpace, SpaceRole } from "~/api/knowledge";
import { cn } from "~/utils";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import { useTranslation } from "react-i18next";

interface KnowledgeSpaceSidebarProps {
    createdSpaces: KnowledgeSpace[];
    joinedSpaces: KnowledgeSpace[];
    activeSpaceId?: string;
    onSpaceSelect: (space: KnowledgeSpace) => void;
    onCreateSpace: () => void;
    onUpdateSpace: (space: KnowledgeSpace) => void;
    onDeleteSpace: (spaceId: string) => void;
    onLeaveSpace: (spaceId: string) => void;
    onPinSpace: (spaceId: string, pinned: boolean) => void;
}

export function KnowledgeSpaceSidebar({
    createdSpaces,
    joinedSpaces,
    activeSpaceId,
    onSpaceSelect,
    onCreateSpace,
    onUpdateSpace,
    onDeleteSpace,
    onLeaveSpace,
    onPinSpace
}: KnowledgeSpaceSidebarProps) {
    const { t } = useTranslation();
    const [searchQuery, setSearchQuery] = useState("");
    const [createdExpanded, setCreatedExpanded] = useState(true);
    const [joinedExpanded, setJoinedExpanded] = useState(true);

    const filterSpaces = (spaces: KnowledgeSpace[]) => {
        if (!searchQuery) return spaces;
        const query = searchQuery.toLowerCase();
        return spaces.filter(space =>
            space.name.toLowerCase().includes(query) ||
            space.description?.toLowerCase().includes(query) ||
            space.tags.some(tag => tag.toLowerCase().includes(query))
        );
    };

    const sortSpaces = (spaces: KnowledgeSpace[]) => {
        return [...spaces].sort((a, b) => {
            if (a.isPinned && !b.isPinned) return -1;
            if (!a.isPinned && b.isPinned) return 1;
            return new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime();
        });
    };

    const renderSpace = (space: KnowledgeSpace) => {
        const isActive = activeSpaceId === space.id;
        const isCreator = space.role === SpaceRole.CREATOR;
        const isAdmin = space.role === SpaceRole.ADMIN;
        const canManage = isCreator || isAdmin;

        return (
            <div
                key={space.id}
                className={cn(
                    "group flex items-center gap-2 px-3 py-2 rounded cursor-pointer hover:bg-[#f7f8fa] transition-colors",
                    isActive && "bg-[#e8f3ff]"
                )}
                onClick={() => onSpaceSelect(space)}
            >
                <Folder className={cn(
                    "size-4 flex-shrink-0",
                    isActive ? "text-[#165dff]" : "text-[#86909c]"
                )} />

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1">
                        <span className={cn(
                            "text-sm truncate",
                            isActive ? "text-[#165dff] font-medium" : "text-[#1d2129]"
                        )}>
                            {space.name}
                        </span>
                        {space.isPinned && (
                            <Pin className="size-3 text-[#ff7d00] fill-[#ff7d00] flex-shrink-0" />
                        )}
                    </div>
                    <div className="text-xs text-[#86909c]">
                        {space.fileCount}/{space.totalFileCount} · {space.memberCount}人
                    </div>
                </div>

                <DropdownMenu>
                    <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
                        <button className="opacity-0 group-hover:opacity-100 p-1 hover:bg-[#e5e6eb] rounded">
                            <MoreVertical className="size-4 text-[#86909c]" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem onClick={(e) => {
                            e.stopPropagation();
                            onPinSpace(space.id, !space.isPinned);
                        }}>
                            {space.isPinned ? "取消置顶" : "置顶"}
                        </DropdownMenuItem>

                        {canManage && (
                            <>
                                <DropdownMenuItem onClick={(e) => {
                                    e.stopPropagation();
                                    // TODO: Open edit dialog
                                }}>
                                    编辑信息
                                </DropdownMenuItem>
                                <DropdownMenuItem onClick={(e) => {
                                    e.stopPropagation();
                                    // TODO: Open member management
                                }}>
                                    成员管理
                                </DropdownMenuItem>
                            </>
                        )}

                        {isCreator ? (
                            <DropdownMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onDeleteSpace(space.id);
                                }}
                                className="text-[#f53f3f]"
                            >
                                解散空间
                            </DropdownMenuItem>
                        ) : (
                            <DropdownMenuItem
                                onClick={(e) => {
                                    e.stopPropagation();
                                    onLeaveSpace(space.id);
                                }}
                                className="text-[#f53f3f]"
                            >
                                退出空间
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            </div>
        );
    };

    const filteredCreated = sortSpaces(filterSpaces(createdSpaces));
    const filteredJoined = sortSpaces(filterSpaces(joinedSpaces));

    return (
        <div className="w-64 border-r border-[#e5e6eb] bg-white flex flex-col h-screen">
            {/* Header */}
            <div className="p-4 border-b border-[#e5e6eb]">
                <div className="flex items-center justify-between mb-3">
                    <h2 className="text-base font-medium text-[#1d2129]">知识空间</h2>
                    <button
                        onClick={onCreateSpace}
                        className="p-1 hover:bg-[#f7f8fa] rounded transition-colors"
                        title="创建空间"
                    >
                        <Plus className="size-4 text-[#4e5969]" />
                    </button>
                </div>

                {/* Search */}
                <div className="relative">
                    <Search className="absolute left-2 top-1/2 -translate-y-1/2 size-4 text-[#86909c]" />
                    <input
                        type="text"
                        placeholder="搜索空间"
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        className="w-full pl-8 pr-3 py-1.5 text-sm border border-[#e5e6eb] rounded focus:outline-none focus:border-[#165dff]"
                    />
                </div>
            </div>

            {/* Space List */}
            <div className="flex-1 overflow-y-auto">
                {/* Created Spaces */}
                {createdSpaces.length > 0 && (
                    <div className="p-2">
                        <button
                            onClick={() => setCreatedExpanded(!createdExpanded)}
                            className="w-full flex items-center gap-1 px-2 py-1 text-xs text-[#86909c] hover:bg-[#f7f8fa] rounded"
                        >
                            {createdExpanded ? (
                                <ChevronDown className="size-3" />
                            ) : (
                                <ChevronRight className="size-3" />
                            )}
                            <span>我创建的 ({filteredCreated.length})</span>
                        </button>
                        {createdExpanded && (
                            <div className="mt-1 space-y-1">
                                {filteredCreated.map(renderSpace)}
                            </div>
                        )}
                    </div>
                )}

                {/* Joined Spaces */}
                {joinedSpaces.length > 0 && (
                    <div className="p-2">
                        <button
                            onClick={() => setJoinedExpanded(!joinedExpanded)}
                            className="w-full flex items-center gap-1 px-2 py-1 text-xs text-[#86909c] hover:bg-[#f7f8fa] rounded"
                        >
                            {joinedExpanded ? (
                                <ChevronDown className="size-3" />
                            ) : (
                                <ChevronRight className="size-3" />
                            )}
                            <span>我加入的 ({filteredJoined.length})</span>
                        </button>
                        {joinedExpanded && (
                            <div className="mt-1 space-y-1">
                                {filteredJoined.map(renderSpace)}
                            </div>
                        )}
                    </div>
                )}

                {/* Empty State */}
                {filteredCreated.length === 0 && filteredJoined.length === 0 && (
                    <div className="flex flex-col items-center justify-center h-full text-center p-4">
                        <Folder className="size-12 text-[#c9cdd4] mb-2" />
                        <p className="text-sm text-[#86909c]">
                            {searchQuery ? "未找到匹配的空间" : "暂无知识空间"}
                        </p>
                        {!searchQuery && (
                            <button
                                onClick={onCreateSpace}
                                className="mt-3 text-sm text-[#165dff] hover:underline"
                            >
                                创建第一个空间
                            </button>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
