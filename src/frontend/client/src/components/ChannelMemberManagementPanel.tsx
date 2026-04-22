import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Search } from "lucide-react";
import {
    getChannelMembersApi,
    removeChannelMemberApi,
    updateChannelMemberRoleApi,
    type ChannelMember,
    ChannelRole,
} from "~/api/channels";
import { NotificationSeverity } from "~/common";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";
import { Button } from "~/components/ui/Button";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "~/components/ui/DropdownMenu";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
} from "~/components/ui/AlertDialog";
import { useLocalize } from "~/hooks";

const PAGE_SIZE = 10;
const MAX_ADMINS = 5;
const MAX_NAME_LEN = 15;
const MAX_GROUP_LEN = 30;
const ROLE_SELECT_WIDTH_CLASS = "h-8 w-24";
const ROLE_SELECT_TRIGGER_CLASS = cn(
    ROLE_SELECT_WIDTH_CLASS,
    "box-border shrink-0 appearance-none rounded-[6px] border-[#EBECF0] bg-white shadow-none",
    "inline-flex items-center justify-end gap-1 px-2 text-[14px] text-[#818181]",
    "hover:border-[#CED4E0] hover:text-[#165DFF]",
);

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

interface ChannelMemberManagementPanelProps {
    channelId: string | null;
    currentUserRole: ChannelRole | null;
    active?: boolean;
}

export function ChannelMemberManagementPanel({
    channelId,
    currentUserRole,
    active = true,
}: ChannelMemberManagementPanelProps) {
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
        [members],
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
                page_size: PAGE_SIZE,
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
        if (!active) return;
        setPage(1);
        void fetchMembers(1);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, channelId]);

    useEffect(() => {
        if (!active) return;
        const timer = setTimeout(() => {
            void fetchMembers(1);
        }, 200);
        return () => clearTimeout(timer);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [active, keyword]);

    const handlePromoteAdmin = async (member: ChannelMember) => {
        if (!channelId || !canCreatorManage) return;
        if (member.role === "admin" || member.role === "creator") return;
        if (adminCount >= MAX_ADMINS) {
            showToast({
                message: localize("com_subscription.exceeded_admin_limit") || "已超出管理员上限",
                severity: NotificationSeverity.WARNING,
            });
            return;
        }
        try {
            await updateChannelMemberRoleApi({
                channel_id: channelId,
                user_id: member.user_id,
                role: "admin",
            });
            await fetchMembers(page);
        } catch {
            showToast({
                message: localize("update_role_failed") || "角色更新失败，请稍后重试",
                severity: NotificationSeverity.ERROR,
            });
        }
    };

    const handleDemoteToMember = async (member: ChannelMember) => {
        if (!channelId || !canCreatorManage) return;
        if (member.role !== "admin") return;
        try {
            await updateChannelMemberRoleApi({
                channel_id: channelId,
                user_id: member.user_id,
                role: "member",
            });
            await fetchMembers(page);
        } catch {
            showToast({
                message: localize("update_role_failed") || "角色更新失败，请稍后重试",
                severity: NotificationSeverity.ERROR,
            });
        }
    };

    const handleRemove = async (member: ChannelMember) => {
        if (!channelId) return;
        try {
            await removeChannelMemberApi({ channel_id: channelId, user_id: member.user_id });
            await fetchMembers(1);
        } catch {
            showToast({
                message: localize("remove_failed") || "移除失败，请稍后重试",
                severity: NotificationSeverity.ERROR,
            });
        }
    };

    const getRoleActionMenu = (member: ChannelMember) => {
        if (!canManageMembers || member.role === "creator") {
            return (
                <span
                    className={cn(
                        ROLE_SELECT_WIDTH_CLASS,
                        "inline-flex items-center justify-end rounded-[6px] px-2 text-[14px] text-[#818181]",
                    )}
                >
                    {getRoleLabel(member.role, localize)}
                </span>
            );
        }

        if (canAdminManage) {
            if (member.role === "admin") {
                return (
                    <span
                        className={cn(
                            ROLE_SELECT_WIDTH_CLASS,
                            "inline-flex items-center justify-end rounded-[6px] px-2 text-[14px] text-[#818181]",
                        )}
                    >
                        {getRoleLabel(member.role, localize)}
                    </span>
                );
            }
            return (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <button type="button" className={ROLE_SELECT_TRIGGER_CLASS}>
                            {getRoleLabel(member.role, localize)}
                            <ChevronDown className="size-3.5" />
                        </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="z-[120] w-28 rounded-[8px] border-[#EBECF0] p-1">
                        <DropdownMenuItem
                            className={cn(
                                "cursor-default",
                                member.role === "member" &&
                                    "bg-[#E8F3FF] text-[#165DFF] data-[highlighted]:bg-[#E8F3FF] data-[highlighted]:text-[#165DFF]",
                            )}
                            onClick={(e) => e.preventDefault()}
                        >
                            {localize("member") || "订阅用户"}
                        </DropdownMenuItem>
                        {member.role === "member" && (
                            <>
                                <DropdownMenuSeparator />
                                <DropdownMenuItem onClick={() => setRemoveTarget(member)}>
                                    {localize("remove")}
                                </DropdownMenuItem>
                            </>
                        )}
                    </DropdownMenuContent>
                </DropdownMenu>
            );
        }

        return (
            <DropdownMenu>
                <DropdownMenuTrigger asChild>
                    <button type="button" className={ROLE_SELECT_TRIGGER_CLASS}>
                        {getRoleLabel(member.role, localize)}
                        <ChevronDown className="size-3.5" />
                    </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end" className="z-[120] w-28 rounded-[8px] border-[#EBECF0] p-1">
                    <DropdownMenuItem
                        className={cn(
                            member.role === "admin" &&
                                "bg-[#E8F3FF] text-[#165DFF] data-[highlighted]:bg-[#E8F3FF] data-[highlighted]:text-[#165DFF]",
                        )}
                        onClick={() => {
                            if (!canCreatorManage || member.role === "admin" || member.role === "creator") return;
                            void handlePromoteAdmin(member);
                        }}
                    >
                        {localize("admin") || "管理员"}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                        className={cn(
                            member.role === "member" &&
                                "bg-[#E8F3FF] text-[#165DFF] data-[highlighted]:bg-[#E8F3FF] data-[highlighted]:text-[#165DFF]",
                        )}
                        onClick={() => {
                            if (!canCreatorManage || member.role === "member") return;
                            void handleDemoteToMember(member);
                        }}
                    >
                        {localize("member") || "订阅用户"}
                    </DropdownMenuItem>
                    {canCreatorManage && (
                        <>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onClick={() => setRemoveTarget(member)}>
                                {localize("remove")}
                            </DropdownMenuItem>
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
        );
    };

    return (
        <>
            <div className="flex min-h-0 flex-1 flex-col">
                <div className="relative mb-4">
                    <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-[#8B8FA8]" />
                    <input
                        value={keyword}
                        onChange={(e) => setKeyword(e.target.value)}
                        placeholder={localize("com_subscription.search_user_placeholder") || "请输入用户名进行搜索"}
                        className="h-8 w-full rounded-[6px] border border-[#EBECF0] pl-9 pr-3 text-[14px] text-[#212121] placeholder:text-[#818181] focus:border-[#165DFF] focus:outline-none"
                    />
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto">
                    {loading ? (
                        <div className="flex h-full items-center justify-center py-10 text-[13px] text-[#86909C]">
                            {localize("loading") || "加载中..."}
                        </div>
                    ) : members.length === 0 ? (
                        <div className="flex h-full flex-col items-center justify-center py-8 text-center">
                            <img
                                className="mb-2 size-[120px] object-contain opacity-90"
                                src={`${__APP_ENV__.BASE_URL}/assets/channel/empty.png`}
                                alt="empty"
                            />
                            <p className="text-[13px] text-[#86909C]">
                                {localize("com_subscription.nofound_mathcing_member")}
                            </p>
                        </div>
                    ) : (
                        members.map((member) => (
                            <div
                                key={member.user_id}
                                className="flex min-h-12 items-center gap-4 border-b border-[#ECECEC] px-0 py-3 last:border-b-0"
                            >
                                <div className="flex min-w-0 flex-1 items-center gap-4">
                                    <div className="flex w-[132px] min-w-[132px] items-center gap-2">
                                        <div className="flex size-8 items-center justify-center rounded-full bg-[#C9CDD4] text-[12px] text-white">
                                            {getInitials(member.user_name)}
                                        </div>
                                        <div
                                            title={member.user_name}
                                            className="min-w-0 flex-1 truncate text-[14px] text-[#212121]"
                                        >
                                            {truncateText(member.user_name, MAX_NAME_LEN)}
                                        </div>
                                    </div>
                                    <div
                                        className="min-w-0 flex-1 truncate text-[12px] text-[#818181]"
                                        title={(member.groups || []).join("、")}
                                    >
                                        {truncateText((member.groups || []).join("、"), MAX_GROUP_LEN)}
                                    </div>
                                </div>
                                <div className="flex w-24 shrink-0 justify-end">
                                    {getRoleActionMenu(member)}
                                </div>
                            </div>
                        ))
                    )}
                </div>
            </div>

            <div className="flex items-center justify-end border-t border-[#ECECEC] px-0 py-4 text-[14px]">
                <div className="flex items-center gap-2">
                    <span className="shrink-0 leading-none text-[14px]">
                        <span className="text-[#4E5969]">{localize("com_subscription.member_pagination_1")}</span>
                        <span className="text-[#165DFF]">{total}</span>
                        <span className="text-[#4E5969]">{localize("com_subscription.member_pagination_2")}</span>
                        <span className="text-[#4E5969]">{PAGE_SIZE}</span>
                        <span className="text-[#4E5969]">{localize("com_subscription.member_pagination_3")}</span>
                    </span>
                    <div className="flex shrink-0 items-center gap-1.5">
                        <Button
                            variant="ghost"
                            className="h-7 w-7 shrink-0 p-0 text-[#4E5969] hover:bg-transparent hover:text-[#165DFF] disabled:opacity-40"
                            disabled={page <= 1}
                            onClick={() => {
                                void fetchMembers(Math.max(1, page - 1));
                            }}
                        >
                            <ChevronLeft className="size-3.5" />
                        </Button>
                        {pageNumbers.map((pageNumber, idx) => {
                            const prev = pageNumbers[idx - 1];
                            const showDots = prev && pageNumber - prev > 1;
                            return (
                                <div key={`page-${pageNumber}`} className="flex items-center gap-1.5">
                                    {showDots && <span className="text-[#4E5969]">...</span>}
                                    <button
                                        type="button"
                                        className={cn(
                                            "flex h-6 min-w-6 items-center justify-center px-1.5 text-[14px] transition-colors",
                                            pageNumber === page
                                                ? "rounded-[8px] border border-[#165DFF] text-[#165DFF]"
                                                : "rounded-[4px] border border-transparent text-[#4E5969] hover:text-[#165DFF]",
                                        )}
                                        onClick={() => {
                                            void fetchMembers(pageNumber);
                                        }}
                                    >
                                        {pageNumber}
                                    </button>
                                </div>
                            );
                        })}
                        <Button
                            variant="ghost"
                            className="h-7 w-7 shrink-0 p-0 text-[#4E5969] hover:bg-transparent hover:text-[#165DFF] disabled:opacity-40"
                            disabled={page >= totalPages}
                            onClick={() => {
                                void fetchMembers(Math.min(totalPages, page + 1));
                            }}
                        >
                            <ChevronRight className="size-3.5" />
                        </Button>
                    </div>
                </div>
            </div>

            <AlertDialog open={!!removeTarget} onOpenChange={(open) => !open && setRemoveTarget(null)}>
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
                                if (removeTarget) {
                                    void handleRemove(removeTarget);
                                }
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
