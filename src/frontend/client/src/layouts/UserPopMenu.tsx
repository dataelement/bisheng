import { ChevronRight } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { useAuthContext } from "~/hooks";
import { useNotificationCount } from "~/hooks/useNotificationCount";
import { settingsLandingPath } from "~/pages/settings/settingsSections";
import { cn } from "~/utils";

/** 左侧窄栏仅头像 = PC；会话历史抽屉内整行 = 移动端 */
export type UserPopMenuVariant = "rail" | "drawer";

export interface UserPopMenuProps {
    variant?: UserPopMenuVariant;
}

/**
 * Avatar entry in the sidebar. The old pop menu (设置 / 消息与审批 / 退出登录) is gone —
 * clicking the avatar goes straight to the settings page, landing on whatever is
 * actually waiting on the user (pending approvals > unread notifications > account).
 * 退出登录 moved into the 账号信息 section of that page.
 */
export function UserPopMenu({ variant = "rail" }: UserPopMenuProps) {
    const isDrawer = variant === "drawer";
    const navigate = useNavigate();

    const { user } = useAuthContext();
    const { unreadCount, pendingApprovalCount } = useNotificationCount();
    const displayName = user?.username || "admin";

    const openSettings = () => {
        navigate(settingsLandingPath(pendingApprovalCount, unreadCount));
    };

    // Avatar edits on the settings page flow back through the user query cache.
    const avatarInner = user?.avatar ? (
        <AvatarImage src={user.avatar} alt="User" />
    ) : (
        <AvatarName name={user?.username} />
    );

    const unreadDot = (unreadCount > 0 || pendingApprovalCount > 0) && (
        <div className="absolute -top-0.5 -right-0.5 z-20 size-2.5 bg-[#f53f3f] rounded-full ring-2 ring-white pointer-events-none" />
    );

    if (isDrawer) {
        return (
            <button
                type="button"
                className={cn(
                    "relative flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left outline-none",
                    "hover:bg-fill-1 transition-colors active:scale-[0.99]",
                )}
                onClick={openSettings}
            >
                <div className="relative shrink-0">
                    <Avatar className="size-9 border border-fill-2">{avatarInner}</Avatar>
                    {unreadDot}
                </div>
                <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium text-text-1 truncate">{displayName}</p>
                </div>
                <ChevronRight className="size-4 shrink-0 text-text-3" aria-hidden />
            </button>
        );
    }

    return (
        <button
            type="button"
            className="relative size-10 cursor-pointer outline-none active:scale-95 transition-transform"
            onClick={openSettings}
        >
            <Avatar className="size-10 hover:opacity-90 transition-opacity">{avatarInner}</Avatar>
            {/* 头像右上角红点 */}
            {unreadDot}
        </button>
    );
}
