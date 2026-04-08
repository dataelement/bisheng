import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Search, X } from "lucide-react";
import {
    type KnowledgeSpace,
    type SpaceMember,
    SpaceRole,
    getSpaceMembersApi,
    removeSpaceMemberApi,
    updateSpaceMemberRoleApi,
} from "~/api/knowledge";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";
import { Button } from "~/components/ui/Button";
import {
    Dialog,
    DialogClose,
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
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle
} from "~/components/ui/AlertDialog";
import { useLocalize } from "~/hooks";

const PAGE_SIZE = 10;
const MAX_ADMINS = 5;
const MAX_NAME_LEN = 15;
const MAX_GROUP_LEN = 30;

function getRoleLabel(role: SpaceMember["role"], localize: (key: string) => string) {
    if (role === "creator") return localize("creator") || "创建者";
    if (role === "admin") return localize("admin") || "管理员";
    return localize("member") || "订阅用户";
}

function roleWeight(role: SpaceMember["role"]) {
    if (role === "creator") return 0;
    if (role === "admin") return 1;
    return 2;
}

function getInitials(name: string) {
    const trimmed = (name || "").trim();
    return (trimmed[0] || "?").toUpperCase();
}

function truncateText(text: string, maxLen: number) {
    if (!text) return "";
    if (text.length <= maxLen) return text;
    return `${text.slice(0, maxLen)}...`;
}

export function KnowledgeSpaceMemberDialog({
    open,
    onOpenChange,
    space
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    space: KnowledgeSpace | null;
}) {
    const { showToast } = useToastContext();
    const localize = useLocalize();
    const [keyword, setKeyword] = useState("");
    const [page, setPage] = useState(1);
    const [loading, setLoading] = useState(false);
    const [members, setMembers] = useState<SpaceMember[]>([]);
    const [removeTarget, setRemoveTarget] = useState<SpaceMember | null>(null);
    const [serverTotal, setServerTotal] = useState(0);

    const currentUserRole = (space?.role || null) as SpaceRole | null;
    const canCreatorManage = currentUserRole === SpaceRole.CREATOR;
    const canAdminManage = currentUserRole === SpaceRole.ADMIN;
    const canManageMembers = canCreatorManage || canAdminManage;

    const filteredMembers = useMemo(() => {
        const kw = keyword.trim().toLowerCase();
        const list = kw
            ? members.filter((m) => (m.user_name || "").toLowerCase().includes(kw))
            : members;
        return [...list].sort((a, b) => {
            const wa = roleWeight(a.role);
            const wb = roleWeight(b.role);
            if (wa !== wb) return wa - wb;
            return (a.user_name || "").localeCompare(b.user_name || "", "zh-Hans-CN");
        });
    }, [members, keyword]);

    const adminCount = useMemo(
        () => members.filter((m) => m.role === "admin").length,
        [members]
    );

    const total = keyword.trim() ? filteredMembers.length : (serverTotal || members.length);
    const totalPages = Math.max(1, Math.ceil(filteredMembers.length / PAGE_SIZE));
    const pagedMembers = useMemo(() => {
        const start = (page - 1) * PAGE_SIZE;
        return filteredMembers.slice(start, start + PAGE_SIZE);
    }, [filteredMembers, page]);

    const pageNumbers = useMemo(() => {
        const maxShow = 5;
        if (totalPages <= maxShow) return Array.from({ length: totalPages }, (_, i) => i + 1);
        if (page <= 3) return [1, 2, 3, 4, totalPages];
        if (page >= totalPages - 2) return [1, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
        return [1, page - 1, page, page + 1, totalPages];
    }, [page, totalPages]);

    const fetchMembers = async () => {
        if (!space?.id) return;
        setLoading(true);
        try {
            const res = await getSpaceMembersApi(space.id);
            setMembers(res.data || []);
            setServerTotal(res.total || 0);
            setPage(1);
        } catch {
            setMembers([]);
            setServerTotal(0);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!open || !space?.id) return;
        fetchMembers();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, space?.id]);

    useEffect(() => {
        setPage(1);
    }, [keyword]);

    const handlePromoteAdmin = async (m: SpaceMember) => {
        if (!space?.id || !canCreatorManage) return;
        if (m.role === "admin" || m.role === "creator") return;
        if (adminCount >= MAX_ADMINS) {
            showToast({
                message: localize("com_subscription.exceeded_admin_limit") || "已超出管理员上限",
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        try {
            await updateSpaceMemberRoleApi(space.id, { user_id: m.user_id, role: "admin" });
            await fetchMembers();
        } catch {
            showToast({
                message: localize("update_role_failed") || "角色更新失败，请稍后重试",
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const handleDemoteToMember = async (m: SpaceMember) => {
        if (!space?.id || !canCreatorManage) return;
        if (m.role !== "admin") return;
        try {
            await updateSpaceMemberRoleApi(space.id, { user_id: m.user_id, role: "member" });
            await fetchMembers();
        } catch {
            showToast({
                message: localize("update_role_failed") || "角色更新失败，请稍后重试",
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const handleRemove = async (m: SpaceMember) => {
        if (!space?.id) return;
        try {
            await removeSpaceMemberApi(space.id, m.user_id);
            await fetchMembers();
            // showToast({
            //     message: localize("remove_success") || "已移除成员",
            //     severity: NotificationSeverity.SUCCESS
            // });
        } catch {
            showToast({
                message: localize("remove_failed") || "移除失败，请稍后重试",
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const getRoleActionMenu = (m: SpaceMember) => {
        if (!canManageMembers || m.role === "creator") {
            return <span className="text-[14px] text-[#999]">{getRoleLabel(m.role, localize)}</span>;
        }

        if (canAdminManage) {
            if (m.role === "admin") {
                return <span className="text-[14px] text-[#999]">{getRoleLabel(m.role, localize)}</span>;
            }
            return (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button className="inline-flex items-center gap-1 text-[14px] text-[#999] hover:text-[#165DFF]">
                            {getRoleLabel(m.role, localize)}
                            <ChevronDown className="size-3.5" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="z-[120] w-28">
                        <DropdownMenuItem
                            className={cn(
                                "cursor-default",
                                m.role === "member" &&
                                    "bg-[#E8F3FF] text-[#165DFF] data-[highlighted]:bg-[#E8F3FF] data-[highlighted]:text-[#165DFF]"
                            )}
                            onClick={(e) => e.preventDefault()}
                        >
                            {localize("member") || "订阅用户"}
                        </DropdownMenuItem>
                        {m.role === "member" && (
                            <DropdownMenuItem onClick={() => setRemoveTarget(m)}>
                                {localize("remove")}
                            </DropdownMenuItem>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            );
        }

        return (
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <button className="inline-flex items-center gap-1 text-[14px] text-[#999] hover:text-[#165DFF]">
                        {getRoleLabel(m.role, localize)}
                        <ChevronDown className="size-3.5" />
                    </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="z-[120] w-28">
                    <DropdownMenuItem
                        className={cn(
                            m.role === "admin" &&
                                "bg-[#E8F3FF] text-[#165DFF] data-[highlighted]:bg-[#E8F3FF] data-[highlighted]:text-[#165DFF]"
                        )}
                        onClick={() => {
                            if (!canCreatorManage || m.role === "admin" || m.role === "creator") return;
                            handlePromoteAdmin(m);
                        }}
                    >
                        {localize("admin") || "管理员"}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        className={cn(
                            m.role === "member" &&
                                "bg-[#E8F3FF] text-[#165DFF] data-[highlighted]:bg-[#E8F3FF] data-[highlighted]:text-[#165DFF]"
                        )}
                        onClick={() => {
                            if (!canCreatorManage || m.role === "member") return;
                            handleDemoteToMember(m);
                        }}
                    >
                        {localize("member") || "订阅用户"}
                    </DropdownMenuItem>
                    {canCreatorManage && (
                        <DropdownMenuItem onClick={() => setRemoveTarget(m)}>
                            {localize("remove")}
                        </DropdownMenuItem>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        );
    };

    if (!open) return null;

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent
                    overlayClassName="z-[100]"
                    className="z-[100] flex h-[600px] w-[700px] max-h-[600px] max-w-[700px] flex-col gap-0 overflow-hidden p-0 rounded-[10px]"
                    close={false}
                >
                    <DialogHeader className="flex shrink-0 flex-row items-center justify-between gap-3 px-6 py-4 sm:text-left">
                        <DialogTitle className="m-0 text-[16px] font-semibold leading-[24px] text-[#1D2129]">
                            {localize("com_subscription.management_member")}
                        </DialogTitle>
                        <DialogClose className="shrink-0 rounded-md p-1 text-[#86909C] opacity-90 outline-none ring-offset-background transition-opacity hover:opacity-100 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2">
                            <X className="size-4"/>
                            <span className="sr-only">Close</span>
                        </DialogClose>
                    </DialogHeader>

                    <div className="flex min-h-0 flex-1 flex-col px-6 pt-3 pb-0">
                        <div className="relative mb-3">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#C9CDD4]" />
                            <input
                                value={keyword}
                                onChange={(e) => setKeyword(e.target.value)}
                                placeholder={localize("com_subscription.search_user_placeholder") || "请输入用户名进行搜索"}
                                className="h-8 w-full rounded-[6px] border border-[#E5E6EB] pl-9 pr-3 text-[14px] text-[#1D2129] placeholder:text-[#999] focus:border-[#165DFF] focus:outline-none"
                            />
                        </div>

                        <div className="min-h-0 flex-1 overflow-y-auto">
                            {loading ? (
                                <div className="h-full flex items-center justify-center text-[13px] text-[#86909C]">
                                    {localize("loading") || "加载中..."}
                                </div>
                            ) : pagedMembers.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center py-8 text-center">
                                    <img
                                        className="size-[120px] mb-2 object-contain opacity-90"
                                        src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                        alt="empty"
                                    />
                                    <p className="text-[13px] text-[#86909C]">
                                        {localize("com_subscription.nofound_mathcing_member")}
                                    </p>
                                </div>
                            ) : (
                                pagedMembers.map((m) => (
                                    <div
                                        key={m.user_id}
                                        className="flex h-10 items-center gap-2.5 px-1"
                                    >
                                        <div className="w-[200px] min-w-[200px] flex items-center gap-2.5">
                                            <div className="size-6 rounded-full bg-[#C9CDD4] text-white text-[11px] flex items-center justify-center">
                                                {getInitials(m.user_name)}
                                            </div>
                                            <div
                                                title={m.user_name}
                                                className="flex-1 min-w-0 text-[13px] text-[#1D2129] truncate"
                                            >
                                                {truncateText(m.user_name, MAX_NAME_LEN)}
                                            </div>
                                        </div>
                                        <div
                                            className="flex-1 min-w-0 text-[12px] text-[#999] truncate"
                                            title={(m.groups || []).join("、")}
                                        >
                                            {truncateText((m.groups || []).join("、"), MAX_GROUP_LEN)}
                                        </div>
                                        <div className="w-[130px] flex justify-end">
                                            {getRoleActionMenu(m)}
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </div>

                    <div className="flex h-[72px] shrink-0 items-center justify-end px-6 text-[12px]">
                        <div className="flex items-center gap-4">
                        <span className="shrink-0 leading-none">
                            <span className="text-[#4E5969]">{localize("com_subscription.member_pagination_1")}</span>
                            <span className="text-[#165DFF]">{total}</span>
                            <span className="text-[#4E5969]">{localize("com_subscription.member_pagination_2")}</span>
                            <span className="text-[#165DFF]">{PAGE_SIZE}</span>
                            <span className="text-[#4E5969]">{localize("com_subscription.member_pagination_3")}</span>
                        </span>
                        <div className="flex shrink-0 items-center gap-1.5">
                            <Button
                                variant="ghost"
                                className="h-7 w-7 shrink-0 p-0 text-[#4E5969] hover:bg-transparent hover:text-[#165DFF] disabled:opacity-40"
                                disabled={page <= 1}
                                onClick={() => setPage(Math.max(1, page - 1))}
                            >
                                <ChevronLeft className="size-3.5" />
                            </Button>
                            {pageNumbers.map((p, idx) => {
                                const prev = pageNumbers[idx - 1];
                                const showDots = prev && p - prev > 1;
                                return (
                                    <div key={`page-${p}`} className="flex items-center gap-1.5">
                                        {showDots && <span className="text-[#4E5969]">...</span>}
                                        <button
                                            type="button"
                                            className={cn(
                                                "flex h-6 min-w-6 items-center justify-center rounded-[4px] px-1.5 text-[12px] transition-colors",
                                                p === page
                                                    ? "border border-[#165DFF] text-[#165DFF]"
                                                    : "border border-transparent text-[#4E5969] hover:text-[#165DFF]"
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
                                className="h-7 w-7 shrink-0 p-0 text-[#4E5969] hover:bg-transparent hover:text-[#165DFF] disabled:opacity-40"
                                disabled={page >= totalPages}
                                onClick={() => setPage(Math.min(totalPages, page + 1))}
                            >
                                <ChevronRight className="size-3.5" />
                            </Button>
                        </div>
                        </div>
                    </div>
                </DialogContent>
            </Dialog>

            <AlertDialog open={!!removeTarget} onOpenChange={(v) => !v && setRemoveTarget(null)}>
                <AlertDialogContent className="max-w-sm">
                    <AlertDialogHeader>
                        <AlertDialogTitle className="text-[16px]">
                            {localize("com_subscription.remove_member")}
                        </AlertDialogTitle>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                        <AlertDialogCancel onClick={() => setRemoveTarget(null)}>
                            {localize("com_subscription.cancel")}
                        </AlertDialogCancel>
                        <AlertDialogAction
                            className={cn("bg-[#F53F3F] hover:bg-[#F76965]")}
                            onClick={() => {
                                if (removeTarget) handleRemove(removeTarget);
                                setRemoveTarget(null);
                            }}
                        >
                            {localize("com_subscription.confirm_removal")}
                        </AlertDialogAction>
                    </AlertDialogFooter>
                </AlertDialogContent>
            </AlertDialog>
        </>
    );
}

