import { Badge } from "@bisheng/ui";
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { useAuthContext, usePrefersMobileLayout } from "~/hooks";
import { useNotificationCount } from "~/hooks/useNotificationCount";
import {
    createSettingsRouteState,
    readSettingsRouteState,
} from "~/pages/settings/settingsHistory";
import { settingsLandingPath } from "~/pages/settings/settingsSections";
import { cn } from "~/utils";

/** rail = avatar only (mobile icon rail); drawer = full row in the mobile history drawer;
 *  sidebar = compact 24px avatar + name row in the desktop workbench sidebar. */
export type UserPopMenuVariant = "rail" | "drawer" | "sidebar";

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
    const location = useLocation();

    const { user } = useAuthContext();
    const { unreadCount, pendingApprovalCount } = useNotificationCount();
    const isMobile = usePrefersMobileLayout();
    const displayName = user?.username || "admin";

    const openSettings = () => {
        // Mobile always lands on the settings menu screen; picking a module is a
        // second, explicit step there. Desktop keeps the "whatever is waiting wins" landing.
        const target = isMobile ? "/settings" : settingsLandingPath(pendingApprovalCount, unreadCount);
        const alreadyInSettings = /^\/settings(?:\/|$)/.test(location.pathname);
        const state = alreadyInSettings
            ? readSettingsRouteState(location.state)
            : createSettingsRouteState(location, window.history.state?.idx);

        // Reopening the avatar entry while settings is visible must not create a new
        // settings history entry or replace the original return destination.
        navigate(target, { replace: alreadyInSettings, state });
    };

    // Avatar edits on the settings page flow back through the user query cache.
    const avatarInner = user?.avatar ? (
        <AvatarImage src={user.avatar} alt="User" />
    ) : (
        <AvatarName name={user?.username} className={cn(variant === "sidebar" && "text-caption")} />
    );

    // 组件-Badge徽标.md §2/§5 — the corner dot on a round host: the badge pulls
    // itself onto the circumference (`circle`) and carries the 1px page-colored
    // ring, so it stays legible on any avatar art without a hand-placed offset.
    const hasUnread = unreadCount > 0 || pendingApprovalCount > 0;
    const withUnreadDot = (avatar: ReactNode) => (
        <Badge dot={hasUnread} circle className="pointer-events-none">
            {avatar}
        </Badge>
    );

    if (variant === "sidebar") {
        return (
            <button
                type="button"
                // Same row chrome as the sidebar's nav rows: 32px tall, 8px radius, fill-1 on hover.
                className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1 text-left outline-none transition-colors hover:bg-fill-1 focus-visible:bg-fill-1"
                onClick={openSettings}
            >
                {withUnreadDot(<Avatar className="h-6 w-6">{avatarInner}</Avatar>)}
                <span className="min-w-0 truncate text-body text-text-1">{displayName}</span>
            </button>
        );
    }

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
                    {withUnreadDot(<Avatar className="size-9 border border-fill-2">{avatarInner}</Avatar>)}
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
            {withUnreadDot(
                <Avatar className="size-10 hover:opacity-90 transition-opacity">{avatarInner}</Avatar>,
            )}
        </button>
    );
}
