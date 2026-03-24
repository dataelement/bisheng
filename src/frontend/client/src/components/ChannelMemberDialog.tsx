import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import {
    getChannelMembersApi,
    removeChannelMemberApi,
    updateChannelMemberRoleApi,
    type ChannelMember,
    ChannelRole
} from "~/api/channels";
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

const PAGE_SIZE = 10;
const MAX_ADMINS = 5;
const MAX_NAME_LEN = 15;
const MAX_GROUP_LEN = 30;

function getRoleLabel(role: ChannelMember["role"], localize: (key: string) => string) {
    if (role === "creator") return localize("creator") || "创建者";
    if (role === "admin") return localize("admin") || "管理员";
    return localize("member") || "订阅用户";
}

function roleWeight(role: ChannelMember["role"]) {
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

export function ChannelMemberDialog({
    open,
    onOpenChange,
    channelId,
    currentUserRole
}: {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    channelId: string | null;
    currentUserRole: ChannelRole | null;
}) {
    const { showToast } = useToastContext();
    const localize = useLocalize();
    const [keyword, setKeyword] = useState("");
    const [page, setPage] = useState(1);
    const [total, setTotal] = useState(0);
    const [loading, setLoading] = useState(false);
    const [members, setMembers] = useState<ChannelMember[]>([]);
    const [removeTarget, setRemoveTarget] = useState<ChannelMember | null>(null);

    const canCreatorManage = currentUserRole === ChannelRole.CREATOR;
    const canAdminManage = currentUserRole === ChannelRole.ADMIN;
    const canManageMembers = canCreatorManage || canAdminManage;

    const adminCount = useMemo(
        () => members.filter((m) => m.role === "admin").length,
        [members]
    );

    const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

    const pageNumbers = useMemo(() => {
        const maxShow = 5;
        if (totalPages <= maxShow) return Array.from({ length: totalPages }, (_, i) => i + 1);
        if (page <= 3) return [1, 2, 3, 4, totalPages];
        if (page >= totalPages - 2) return [1, totalPages - 3, totalPages - 2, totalPages - 1, totalPages];
        return [1, page - 1, page, page + 1, totalPages];
    }, [page, totalPages]);

    const fetchMembers = async (nextPage: number) => {
        if (!channelId) return;
        setLoading(true);
        try {
            const res = await getChannelMembersApi({
                channel_id: channelId,
                keyword: keyword.trim() || undefined,
                page: nextPage,
                page_size: PAGE_SIZE
            });
            const sorted = [...(res.data || [])].sort((a, b) => {
                const wa = roleWeight(a.role);
                const wb = roleWeight(b.role);
                if (wa !== wb) return wa - wb;
                return (a.user_name || "").localeCompare(b.user_name || "", "zh-Hans-CN");
            });
            setMembers(sorted);
            setTotal(res.total || 0);
            setPage(nextPage);
        } catch {
            setMembers([]);
            setTotal(0);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!open) return;
        setPage(1);
        fetchMembers(1);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [open, channelId]);

    useEffect(() => {
        if (!open) return;
        const t = setTimeout(() => fetchMembers(1), 200);
        return () => clearTimeout(t);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [keyword]);

    const handlePromoteAdmin = async (m: ChannelMember) => {
        if (!channelId) return;
        if (!canCreatorManage) return;
        if (m.role === "admin" || m.role === "creator") return;
        if (adminCount >= MAX_ADMINS) {
            showToast({
                message: localize("exceeded_admin_limit") || "已超出管理员上限",
                severity: NotificationSeverity.WARNING
            });
            return;
        }
        try {
            await updateChannelMemberRoleApi({ channel_id: channelId, user_id: m.user_id, role: "admin" });
            await fetchMembers(page);
            // showToast({
            //     message: localize("update_role_success") || "角色已更新",
            //     severity: NotificationSeverity.SUCCESS
            // });
        } catch {
            showToast({
                message: localize("update_role_failed") || "角色更新失败，请稍后重试",
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const handleDemoteToMember = async (m: ChannelMember) => {
        if (!channelId) return;
        if (!canCreatorManage) return;
        if (m.role !== "admin") return;
        try {
            await updateChannelMemberRoleApi({ channel_id: channelId, user_id: m.user_id, role: "member" });
            await fetchMembers(page);
            // showToast({
            //     message: localize("update_role_success") || "角色已更新",
            //     severity: NotificationSeverity.SUCCESS
            // });
        } catch {
            showToast({
                message: localize("update_role_failed") || "角色更新失败，请稍后重试",
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const handleRemove = async (m: ChannelMember) => {
        if (!channelId) return;
        try {
            await removeChannelMemberApi({ channel_id: channelId, user_id: m.user_id });
            await fetchMembers(1);
            showToast({
                message: localize("remove_success") || "已移除成员",
                severity: NotificationSeverity.SUCCESS
            });
        } catch {
            showToast({
                message: localize("remove_failed") || "移除失败，请稍后重试",
                severity: NotificationSeverity.ERROR
            });
        }
    };

    const getRoleActionMenu = (m: ChannelMember) => {
        if (!canManageMembers || m.role === "creator") {
            return <span className="text-[14px] text-[#4E5969]">{getRoleLabel(m.role, localize)}</span>;
        }

        // 管理员视角：不展示「管理员」选项；仅允许移除普通成员
        if (canAdminManage) {
            if (m.role === "admin") {
                return <span className="text-[14px] text-[#4E5969]">{getRoleLabel(m.role, localize)}</span>;
            }
            return (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button className="inline-flex items-center gap-1 text-[14px] text-[#4E5969] hover:text-[#165DFF]">
                            {getRoleLabel(m.role, localize)}
                            <ChevronDown className="size-3.5" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-28">
                        <DropdownMenuItem
                            className={cn(
                                "cursor-default",
                                m.role === "member" && "bg-[#E8F3FF] text-[#165DFF]"
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
                    <button className="inline-flex items-center gap-1 text-[14px] text-[#4E5969] hover:text-[#165DFF]">
                        {getRoleLabel(m.role, localize)}
                        <ChevronDown className="size-3.5" />
                    </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="w-28">
                    <DropdownMenuItem
                        className={cn(m.role === "admin" && "bg-[#E8F3FF] text-[#165DFF]")}
                        onClick={() => {
                            if (!canCreatorManage || m.role === "admin" || m.role === "creator") return;
                            handlePromoteAdmin(m);
                        }}
                    >
                        {localize("admin") || "管理员"}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        className={cn(m.role === "member" && "bg-[#E8F3FF] text-[#165DFF]")}
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
                <DialogContent className="max-w-[760px] p-0 gap-0 rounded-[10px]" close={true}>
                    <DialogHeader className="px-5 pt-5 pb-3 border-b border-[#E5E6EB]">
                        <DialogTitle className="text-[16px] text-[#1D2129]">
                            {localize("com_subscription.management_member")}
                        </DialogTitle>
                    </DialogHeader>

                    <div className="px-5 pt-3 pb-0">
                        <div className="relative mb-3">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 size-4 text-[#C9CDD4]" />
                            <input
                                value={keyword}
                                onChange={(e) => setKeyword(e.target.value)}
                                placeholder={localize("com_subscription.search_user_placeholder") || "请输入用户名进行搜索"}
                                className="w-full h-9 pl-9 pr-3 rounded border border-[#E5E6EB] text-[14px] focus:outline-none focus:border-[#165DFF]"
                            />
                        </div>

                        <div className="h-[360px] overflow-y-auto">
                            {loading ? (
                                <div className="h-full flex items-center justify-center text-[13px] text-[#86909C]">
                                    {localize("loading") || "加载中..."}
                                </div>
                            ) : members.length === 0 ? (
                                <div className="h-full flex items-center justify-center text-[13px] text-[#86909C]">
                                    {localize("com_subscription.nofound_mathcing_member")}
                                </div>
                            ) : (
                                members.map((m) => (
                                    <div
                                        key={m.user_id}
                                        className="h-10 px-1 flex items-center gap-2.5 border-b border-[#F2F3F5] last:border-0"
                                    >
                                        <div className="size-6 rounded-full bg-[#C9CDD4] text-white text-[11px] flex items-center justify-center">
                                            {getInitials(m.user_name)}
                                        </div>
                                        <div
                                            title={m.user_name}
                                            className="w-[220px] text-[13px] text-[#1D2129] truncate"
                                        >
                                            {truncateText(m.user_name, MAX_NAME_LEN)}
                                        </div>
                                        <div
                                            className="flex-1 min-w-0 text-[12px] text-[#86909C] truncate"
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

                    <div className="h-11 px-5 border-t border-[#E5E6EB] flex items-center justify-between text-[12px] text-[#4E5969]">
                        <span className="text-[#86909C]">
                            {localize("com_subscription.total_members") || "总成员数"}：
                            <span className="text-[#165DFF] ml-1">{total}</span>
                        </span>
                        <div className="flex items-center gap-1.5">
                            <Button
                                variant="ghost"
                                className="h-7 w-7 p-0 text-[#86909C] disabled:opacity-40"
                                disabled={page <= 1}
                                onClick={() => fetchMembers(Math.max(1, page - 1))}
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
                                            onClick={() => fetchMembers(p)}
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
                                onClick={() => fetchMembers(Math.min(totalPages, page + 1))}
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

