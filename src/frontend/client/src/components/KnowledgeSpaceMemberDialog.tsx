import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import { SpaceRole, type KnowledgeSpace } from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";
import { Button } from "~/components/ui/Button";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle
} from "~/components/ui/Dialog";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle
} from "~/components/ui/AlertDialog";
import { useLocalize } from "~/hooks";

const MAX_ADMINS = 5;
const MAX_NAME_LEN = 15;
const MAX_GROUP_LEN = 30;
const PAGE_SIZE = 10;

interface SpaceMember {
    id: string;
    name: string;
    groups: string[];
    role: SpaceRole;
}

interface KnowledgeSpaceMemberDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    space: KnowledgeSpace | null;
}

function truncateText(text: string, maxLen: number) {
    if (text.length <= maxLen) return text;
    return `${text.slice(0, maxLen)}...`;
}

function getRoleLabel(role: SpaceRole) {
    if (role === SpaceRole.CREATOR) return "创建者";
    if (role === SpaceRole.ADMIN) return "管理员";
    return "订阅用户";
}

function makeMemberSeed(space: KnowledgeSpace): SpaceMember[] {
    const fixed: SpaceMember[] = [
        {
            id: `${space.id}-creator`,
            name: space.creator || "空间创建者",
            groups: ["一号用户组", "二号用户组", "三号用户组", "四号用户组"],
            role: SpaceRole.CREATOR
        },
        {
            id: `${space.id}-admin-1`,
            name: "admin@example.com",
            groups: ["一号用户组", "二号用户组", "三号用户组", "四号用户组"],
            role: SpaceRole.ADMIN
        },
        {
            id: `${space.id}-admin-2`,
            name: "alpha.admin",
            groups: ["运维组", "知识库共建组"],
            role: SpaceRole.ADMIN
        },
        {
            id: `${space.id}-member-1`,
            name: "张三-超长用户名用于截断展示示例",
            groups: ["运营一组", "内容采编组", "日报订阅组", "测试长组名展示"],
            role: SpaceRole.MEMBER
        },
        {
            id: `${space.id}-member-2`,
            name: "李四",
            groups: ["内容审核组"],
            role: SpaceRole.MEMBER
        },
        {
            id: `${space.id}-member-3`,
            name: "王五",
            groups: ["数据标注组", "语料治理组"],
            role: SpaceRole.MEMBER
        },
        {
            id: `${space.id}-member-4`,
            name: "zhao_ming",
            groups: ["外部协作组"],
            role: SpaceRole.MEMBER
        },
        {
            id: `${space.id}-member-5`,
            name: "chenyu",
            groups: ["财务分析组"],
            role: SpaceRole.MEMBER
        }
    ];
    return fixed;
}

function roleWeight(role: SpaceRole) {
    if (role === SpaceRole.CREATOR) return 0;
    if (role === SpaceRole.ADMIN) return 1;
    return 2;
}

function getInitials(name: string) {
    const trimmed = name.trim();
    return (trimmed[0] || "?").toUpperCase();
}

export function KnowledgeSpaceMemberDialog({
    open,
    onOpenChange,
    space
}: KnowledgeSpaceMemberDialogProps) {
    const { showToast } = useToastContext();
    const localize = useLocalize();
    const [search, setSearch] = useState("");
    const [membersBySpace, setMembersBySpace] = useState<Record<string, SpaceMember[]>>({});
    const [removeTarget, setRemoveTarget] = useState<SpaceMember | null>(null);
    const [page, setPage] = useState(1);

    const spaceMembers = useMemo(() => {
        if (!space) return [];
        return membersBySpace[space.id] || makeMemberSeed(space);
    }, [membersBySpace, space]);

    const currentRole = space?.role;
    const canCreatorManage = currentRole === SpaceRole.CREATOR;
    const canAdminManage = currentRole === SpaceRole.ADMIN;
    const canManageMembers = canCreatorManage || canAdminManage;

    const filteredAndSortedMembers = useMemo(() => {
        const query = search.trim().toLowerCase();
        const filtered = query
            ? spaceMembers.filter((m) => m.name.toLowerCase().includes(query))
            : spaceMembers;
        return [...filtered].sort((a, b) => {
            const wa = roleWeight(a.role);
            const wb = roleWeight(b.role);
            if (wa !== wb) return wa - wb;
            return a.name.localeCompare(b.name, "zh-Hans-CN");
        });
    }, [search, spaceMembers]);

    const adminCount = useMemo(
        () => spaceMembers.filter((m) => m.role === SpaceRole.ADMIN).length,
        [spaceMembers]
    );

    const totalPages = Math.max(1, Math.ceil(filteredAndSortedMembers.length / PAGE_SIZE));
    const pagedMembers = useMemo(() => {
        const start = (page - 1) * PAGE_SIZE;
        return filteredAndSortedMembers.slice(start, start + PAGE_SIZE);
    }, [filteredAndSortedMembers, page]);

    const pageNumbers = useMemo(() => {
        const maxShow = 5;
        if (totalPages <= maxShow) {
            return Array.from({ length: totalPages }, (_, i) => i + 1);
        }
        if (page <= 3) return [1, 2, 3, 4, totalPages];
        if (page >= totalPages - 2) return [1, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
        return [1, page - 1, page, page + 1, totalPages];
    }, [page, totalPages]);

    useEffect(() => {
        setPage(1);
    }, [search, open, space?.id]);

    const setMemberRole = (memberId: string, role: SpaceRole) => {
        if (!space) return;
        setMembersBySpace((prev) => {
            const current = prev[space.id] || makeMemberSeed(space);
            const next = current.map((m) => (m.id === memberId ? { ...m, role } : m));
            return { ...prev, [space.id]: next };
        });
    };

    const removeMember = (memberId: string) => {
        if (!space) return;
        setMembersBySpace((prev) => {
            const current = prev[space.id] || makeMemberSeed(space);
            const next = current.filter((m) => m.id !== memberId);
            return { ...prev, [space.id]: next };
        });
    };

    const handlePromoteAdmin = (member: SpaceMember) => {
        if (member.role === SpaceRole.ADMIN) return;
        if (adminCount >= MAX_ADMINS) {
            showToast({
                message: localize("exceeded_admin_limit") || "已超出管理员上限",
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        setMemberRole(member.id, SpaceRole.ADMIN);
    };

    const handleDemoteToMember = (member: SpaceMember) => {
        if (member.role === SpaceRole.MEMBER) return;
        setMemberRole(member.id, SpaceRole.MEMBER);
    };

    const getGroupText = (member: SpaceMember) => member.groups.join("、");

    const getRoleActionMenu = (member: SpaceMember) => {
        if (!canManageMembers || member.role === SpaceRole.CREATOR) {
            return (
                <span className="text-[14px] text-[#4E5969]">
                    {getRoleLabel(member.role)}
                </span>
            );
        }

        if (canAdminManage && member.role === SpaceRole.ADMIN) {
            return (
                <span className="text-[14px] text-[#4E5969]">
                    {getRoleLabel(member.role)}
                </span>
            );
        }

        return (
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <button className="inline-flex items-center gap-1 text-[14px] text-[#4E5969] hover:text-[#165DFF]">
                        {getRoleLabel(member.role)}
                        <ChevronDown className="size-3.5" />
                    </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-32">
                    {canCreatorManage && (
                        <DropdownMenuItem onClick={() => handlePromoteAdmin(member)}>
                            管理员
                        </DropdownMenuItem>
                    )}
                    {canCreatorManage && (
                        <DropdownMenuItem onClick={() => handleDemoteToMember(member)}>
                            订阅用户
                        </DropdownMenuItem>
                    )}
                    {(canCreatorManage || (canAdminManage && member.role === SpaceRole.MEMBER)) && (
                        <DropdownMenuItem
                            className=""
                            onClick={() => setRemoveTarget(member)}
                        >
                            移除
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        );
    };

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent className="max-w-[760px] p-0 gap-0 rounded-[10px]" close={true}>
                    <DialogHeader className="px-5 pt-5 pb-3 border-b border-[#E5E6EB]">
                        <DialogTitle className="text-[16px] text-[#1D2129]">
                            {localize("management_member")}
                        </DialogTitle>
                    </DialogHeader>

                    <div className="px-5 pt-3 pb-0">
                        <div className="relative mb-3">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#C9CDD4]" />
                            <input
                                value={search}
                                onChange={(e) => setSearch(e.target.value)}
                                placeholder={localize("search_user_placeholder") || "请输入用户名进行搜索"}
                                className="w-full h-9 pl-9 pr-3 rounded border border-[#E5E6EB] text-[14px] focus:outline-none focus:border-[#165DFF]"
                            />
                        </div>

                        <div className="h-[360px] overflow-y-auto">
                            {pagedMembers.length === 0 ? (
                                <div className="h-full flex items-center justify-center text-[13px] text-[#86909C]">
                                    {localize("nofound_mathcing_member")}
                                </div>
                            ) : (
                                pagedMembers.map((member) => {
                                    const groupText = getGroupText(member);
                                    return (
                                        <div
                                            key={member.id}
                                            className="h-10 px-1 flex items-center gap-2.5 border-b border-[#F2F3F5] last:border-0"
                                        >
                                            <div className="size-6 rounded-full bg-[#C9CDD4] text-white text-[11px] flex items-center justify-center">
                                                {getInitials(member.name)}
                                            </div>
                                            <div
                                                title={member.name}
                                                className="w-[160px] text-[13px] text-[#1D2129] truncate"
                                            >
                                                {truncateText(member.name, MAX_NAME_LEN)}
                                            </div>
                                            <div
                                                title={groupText}
                                                className="flex-1 min-w-0 text-[12px] text-[#86909C] truncate"
                                            >
                                                {truncateText(groupText, MAX_GROUP_LEN)}
                                            </div>
                                            <div className="w-[110px] flex justify-end">
                                                {getRoleActionMenu(member)}
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>
                    </div>

                    <div className="h-11 px-5 border-t border-[#E5E6EB] flex items-center justify-between text-[12px] text-[#4E5969]">
                        <span className="text-[#86909C]">
                            共 <span className="text-[#165DFF]">{filteredAndSortedMembers.length}</span> 条数据，每页 {PAGE_SIZE} 条
                        </span>
                        <div className="flex items-center gap-1.5">
                            <Button
                                variant="ghost"
                                className="h-7 w-7 p-0 text-[#86909C] disabled:opacity-40"
                                disabled={page <= 1}
                                onClick={() => setPage((p) => Math.max(1, p - 1))}
                            >
                                <ChevronLeft className="size-3.5" />
                            </Button>
                            {pageNumbers.map((p, idx) => {
                                const prev = pageNumbers[idx - 1];
                                const showDots = prev && p - prev > 1;
                                return (
                                    <div key={`page-${p}`} className="flex items-center gap-1.5">
                                        {showDots && <span className="text-[#86909C]">...</span>}
                                        <button
                                            className={cn(
                                                "h-6 min-w-6 px-1 rounded-full text-[12px] border transition-colors",
                                                p === page
                                                    ? "border-[#165DFF] text-[#165DFF]"
                                                    : "border-transparent text-[#4E5969] hover:text-[#165DFF]"
                                            )}
                                            onClick={() => setPage(p)}
                                        >
                                            {p}
                                        </button>
                                    </div>
                                );
                            })}
                            <Button
                                variant="ghost"
                                className="h-7 w-7 p-0 text-[#86909C] disabled:opacity-40"
                                disabled={page >= totalPages}
                                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                            >
                                <ChevronRight className="size-3.5" />
                            </Button>
                        </div>
                    </div>
                </DialogContent>
            </Dialog>

            <AlertDialog open={!!removeTarget} onOpenChange={(v) => !v && setRemoveTarget(null)}>
                <AlertDialogContent className="max-w-sm">
                    <AlertDialogHeader>
                        <AlertDialogTitle className="text-[16px]">
                            {localize("remove_member")}
                        </AlertDialogTitle>
                        <AlertDialogDescription>
                            确认将 “{removeTarget?.name}” 移出该频道库吗？
                        </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel onClick={() => setRemoveTarget(null)}>
                            {localize("cancel")}
                        </AlertDialogCancel>
                        <AlertDialogAction
                            className={cn("bg-[#F53F3F] hover:bg-[#F76965]")}
                            onClick={() => {
                                if (removeTarget) removeMember(removeTarget.id);
                                setRemoveTarget(null);
                            }}
                        >
                            {localize("confirm_removal")}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}

