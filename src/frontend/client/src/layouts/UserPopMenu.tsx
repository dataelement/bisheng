import { Badge } from "@bisheng/ui";
import type { ReactNode } from "react";
import { ChevronRight } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { UserAvatar } from "~/components/ui/Avatar";
import { useAuthContext, useLocalize, usePrefersMobileLayout } from "~/hooks";
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
    onNavigate?: () => void;
}

/**
 * Clicking the sidebar avatar opens the settings page, landing on whatever is
 * actually waiting on the user (pending approvals > unread notifications > account).
 */
export function UserPopMenu({ variant = "rail", onNavigate }: UserPopMenuProps) {
    const isDrawer = variant === "drawer";
    const navigate = useNavigate();
    const location = useLocation();
    const localize = useLocalize();

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
        onNavigate?.();
    };

    // The badge's circle mode insets the dot onto the avatar circumference.
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
                className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-2 py-1 text-left outline-none transition-colors hover:bg-fill-1 focus-visible:bg-fill-1 coarse-pointer:min-h-11"
                onClick={openSettings}
            >
                {withUnreadDot(<UserAvatar className="size-6" fallbackClassName="text-caption" name={user?.username} src={user?.avatar} />)}
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
                    {withUnreadDot(<UserAvatar className="size-9 border border-fill-2" name={user?.username} src={user?.avatar} />)}
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
            aria-label={localize("com_nav_settings")}
            className="relative size-10 cursor-pointer outline-none active:scale-95 transition-transform"
            onClick={openSettings}
        >
            {withUnreadDot(
                <UserAvatar className="size-10 hover:opacity-90 transition-opacity" name={user?.username} src={user?.avatar} />,
            )}
        </button>
    );
}
