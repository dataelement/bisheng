import { ChevronRight } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { MessageApprovalDialog, type MessageApprovalTarget } from "~/components/messageApproval/MessageApprovalDialog";
import { SettingsDialog } from "~/components/Settings/SettingsDialog";
import { useSettingsDialog } from "~/components/Settings/useSettingsDialog";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { DropdownMenu, DropdownMenuTrigger } from "~/components/ui/DropdownMenu";
import { ActionMenuContent } from "~/components/ActionMenu";
import { useAuthContext, useLocalize } from "~/hooks";
import { useNotificationCount } from "~/hooks/useNotificationCount";
import { useNotificationsFromUrl } from "~/hooks/useNotificationsFromUrl";
import { cn } from "~/utils";

/** 左侧窄栏仅头像 = PC；会话历史抽屉内整行 = 移动端，菜单内容与 PC 一致 */
export type UserPopMenuVariant = "rail" | "drawer";

export interface UserPopMenuProps {
    variant?: UserPopMenuVariant;
}

type MenuAction = "settings" | "message_approval" | "logout";

interface MenuRowProps {
    icon: ReactNode;
    label: string;
    danger?: boolean;
    badge?: ReactNode;
    onClick: () => void;
}

function MenuRow({ icon, label, danger, badge, onClick }: MenuRowProps) {
    return (
        <button
            type="button"
            className={cn(
                "flex w-full items-center justify-between gap-3 rounded-lg px-3 py-1.5 text-left outline-none transition-colors",
                danger ? "text-[#f53f3f] hover:bg-red-50" : "text-gray-700 hover:bg-[#f2f3f5]",
            )}
            onClick={onClick}
        >
            <div className="flex min-w-0 items-center gap-3">
                <span className={cn("shrink-0 [&>svg]:size-[18px]", !danger && "text-gray-600")}>{icon}</span>
                <span className={cn("truncate text-[14px]", danger && "font-medium")}>{label}</span>
            </div>
            {badge}
        </button>
    );
}

interface MenuBodyProps {
    avatarInner: ReactNode;
    displayName: string;
    /** Approval tasks waiting on this user — shown as a number. */
    pendingApprovalCount: number;
    /** Unread notifications — only downgrades the badge to a dot when there is nothing to handle. */
    unreadCount: number;
    onAction: (action: MenuAction) => void;
}

/** Menu content shared verbatim by the rail dropdown and the drawer inline panel. */
function MenuBody({ avatarInner, displayName, pendingApprovalCount, unreadCount, onAction }: MenuBodyProps) {
    const localize = useLocalize();
    // Pending approvals are the actionable count, so they win the numeric badge. Unread
    // notifications alone only earn a dot — the two are never summed into one total.
    const displayPendingCount = pendingApprovalCount > 99 ? "99+" : String(pendingApprovalCount);

    return (
        <>
            {/* User header — display only; the settings row below is the entry point */}
            <div className="flex w-full min-w-0 items-center gap-3 px-3 py-1.5">
                <Avatar className="size-9 shrink-0 border border-gray-100">{avatarInner}</Avatar>
                <span className="min-w-0 truncate text-[14px] font-medium text-gray-900">
                    {displayName}
                </span>
            </div>

            <div className="mx-3 my-1 h-px bg-gray-100" />

            <MenuRow
                icon={<Outlined.Seal />}
                label={localize("com_message_approval_title")}
                badge={
                    pendingApprovalCount > 0 ? (
                        <span className="flex h-5 min-w-[20px] shrink-0 items-center justify-center rounded-full bg-[#f53f3f] px-1.5 text-[12px] leading-none text-white tabular-nums">
                            {displayPendingCount}
                        </span>
                    ) : unreadCount > 0 ? (
                        <span className="size-2 shrink-0 rounded-full bg-[#f53f3f]" />
                    ) : undefined
                }
                onClick={() => onAction("message_approval")}
            />

            <MenuRow
                icon={<Outlined.Setting />}
                label={localize("com_nav_settings")}
                onClick={() => onAction("settings")}
            />

            <MenuRow
                danger
                icon={<Outlined.LogOut />}
                label={localize("com_nav_log_out")}
                onClick={() => onAction("logout")}
            />
        </>
    );
}

export function UserPopMenu({ variant = "rail" }: UserPopMenuProps) {
    const isDrawer = variant === "drawer";

    // Drawer: inline panel (no Portal, must not exceed the sidebar width). Rail: Radix dropdown.
    const [menuOpen, setMenuOpen] = useState(false);
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);
    const triggerRef = useRef<HTMLDivElement>(null);
    const [menuAlignOffset, setMenuAlignOffset] = useState(0);
    const [menuSideOffset, setMenuSideOffset] = useState(0);
    /** 避免打开瞬间菜单盖住头像时，同一套 pointer 事件的 click 落到下方菜单项（如退出登录） */
    const suppressMenuItemClicksRef = useRef(false);

    const { user, logout } = useAuthContext();
    const { unreadCount, pendingApprovalCount, refreshCount } = useNotificationCount();
    const displayName = user?.username || "admin";
    const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");

    const settings = useSettingsDialog();
    const [messageApprovalTarget, setMessageApprovalTarget] = useState<MessageApprovalTarget | undefined>(undefined);
    // `?open-notifications=1` deep links land on the notification section of the merged dialog.
    const { open: dialogOpen, setOpen: setDialogOpen } = useNotificationsFromUrl();
    // The hook seeds `open` from the URL at mount, so an initially-open dialog came from a
    // ?open-notifications deep link — which always means the notification inbox.
    const openedFromUrlRef = useRef(dialogOpen);
    useEffect(() => {
        if (openedFromUrlRef.current) setMessageApprovalTarget({ section: "notifications" });
    }, []);

    const closeMenu = () => {
        setMenuOpen(false);
        setDropdownOpen(false);
    };

    const handleDialogOpenChange = (open: boolean) => {
        setDialogOpen(open);
        if (!open) {
            void refreshCount();
        }
    };

    const handleAction = (action: MenuAction) => {
        if (!isDrawer && suppressMenuItemClicksRef.current) return;
        closeMenu();
        switch (action) {
            case "settings":
                settings.openSettings("account");
                break;
            case "message_approval":
                // Let the dialog pick its landing section from the pending count.
                setMessageApprovalTarget(undefined);
                setDialogOpen(true);
                break;
            case "logout":
                logout();
                break;
        }
    };

    // Drawer: close on outside pointer-down / Escape; refresh unread count on open
    useEffect(() => {
        if (!isDrawer || !menuOpen) return;
        void refreshCount();
        const onPointerDown = (e: PointerEvent) => {
            const el = rootRef.current;
            if (el && !el.contains(e.target as Node)) {
                setMenuOpen(false);
            }
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") setMenuOpen(false);
        };
        document.addEventListener("pointerdown", onPointerDown, true);
        window.addEventListener("keydown", onKey);
        return () => {
            document.removeEventListener("pointerdown", onPointerDown, true);
            window.removeEventListener("keydown", onKey);
        };
    }, [isDrawer, menuOpen, refreshCount]);

    const handleDropdownOpenChange = (nextOpen: boolean) => {
        setDropdownOpen(nextOpen);
        if (nextOpen) {
            suppressMenuItemClicksRef.current = true;
            window.setTimeout(() => {
                suppressMenuItemClicksRef.current = false;
            }, 400);
        } else {
            suppressMenuItemClicksRef.current = false;
        }
        // Refresh the unread count whenever the menu opens or closes
        void refreshCount();
    };

    useLayoutEffect(() => {
        if (isDrawer || !dropdownOpen) {
            setMenuAlignOffset(0);
            setMenuSideOffset(0);
            return;
        }
        const measure = () => {
            const el = triggerRef.current;
            if (!el) return;
            const r = el.getBoundingClientRect();
            const marginX = 8;
            const marginBottom = 8;
            // 与视口：左缘 8px；底缘 8px（side=top + sideOffset 将菜单底侧锚到视口底上方）
            setMenuAlignOffset(marginX - Math.round(r.left));
            setMenuSideOffset(Math.round(r.top - (window.innerHeight - marginBottom)));
        };
        measure();
        window.addEventListener("resize", measure);
        return () => window.removeEventListener("resize", measure);
    }, [isDrawer, dropdownOpen]);

    const avatarInner = avatarUrl ? (
        <AvatarImage src={avatarUrl} alt="User" />
    ) : user?.avatar ? (
        <AvatarImage src={user.avatar} alt="User" />
    ) : (
        <AvatarName name={user?.username} />
    );

    const unreadDot = (unreadCount > 0 || pendingApprovalCount > 0) && (
        <div className="absolute -top-0.5 -right-0.5 z-20 size-2.5 bg-[#f53f3f] rounded-full ring-2 ring-white pointer-events-none" />
    );

    const menuBody = (
        <MenuBody
            avatarInner={avatarInner}
            displayName={displayName}
            pendingApprovalCount={pendingApprovalCount}
            unreadCount={unreadCount}
            onAction={handleAction}
        />
    );

    const dialogs = (
        <>
            <SettingsDialog
                open={settings.open}
                onOpenChange={settings.setOpen}
                section={settings.section}
                onSectionChange={settings.setSection}
                username={displayName}
                avatarUrl={avatarUrl || user?.avatar || ""}
                onAvatarUpdated={(url) => setAvatarUrl(url)}
            />

            <MessageApprovalDialog
                open={dialogOpen}
                onOpenChange={handleDialogOpenChange}
                target={messageApprovalTarget}
                pendingApprovalCount={pendingApprovalCount}
                unreadNotificationCount={unreadCount}
                onCountsMaybeChanged={refreshCount}
            />
        </>
    );

    if (isDrawer) {
        return (
            <div ref={rootRef} className="relative w-full">
                <button
                    type="button"
                    aria-expanded={menuOpen}
                    className={cn(
                        "relative z-10 flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left outline-none",
                        "hover:bg-fill-1 transition-colors active:scale-[0.99]",
                        // 打开时透明但保留命中区域，避免 pointer-events-none 导致点击穿透到下层
                        menuOpen && "opacity-0",
                    )}
                    onClick={() => setMenuOpen((open) => !open)}
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

                {menuOpen ? (
                    <div
                        role="menu"
                        className="absolute bottom-0 left-0 right-0 z-[70] max-w-full rounded-2xl border border-[#f0f0f0] bg-white p-2 shadow-[0_4px_20px_rgba(0,0,0,0.08)]"
                    >
                        {menuBody}
                    </div>
                ) : null}

                {dialogs}
            </div>
        );
    }

    return (
        <>
            <DropdownMenu open={dropdownOpen} onOpenChange={handleDropdownOpenChange}>
                <DropdownMenuTrigger asChild>
                    <div
                        ref={triggerRef}
                        className="relative size-10 cursor-pointer outline-none active:scale-95 transition-transform"
                    >
                        <Avatar className="size-10 hover:opacity-90 transition-opacity">{avatarInner}</Avatar>
                        {/* 头像右上角红点 */}
                        {unreadDot}
                    </div>
                </DropdownMenuTrigger>

                <ActionMenuContent
                    side="top"
                    align="start"
                    width={200}
                    alignOffset={menuAlignOffset}
                    sideOffset={menuSideOffset}
                    collisionPadding={8}
                    onCloseAutoFocus={(e) => e.preventDefault()}
                >
                    {menuBody}
                </ActionMenuContent>
            </DropdownMenu>

            {dialogs}
        </>
    );
}
