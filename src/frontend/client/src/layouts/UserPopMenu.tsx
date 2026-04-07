import { Bell, Globe, LogOut, ChevronRight, Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRecoilState } from "recoil";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSub,
    DropdownMenuSubTrigger,
    DropdownMenuSubContent
} from "~/components/ui/DropdownMenu";
import { AccountInfoDialog } from "~/components/AccountInfoDialog";
import { NotificationsDialog } from "~/components/NotificationsDialog";
import { useNotificationCount } from "~/hooks/useNotificationCount";
import { useAuthContext, useLocalize } from "~/hooks";
import store from "~/store";
import { cn } from "~/utils";

/** 左侧窄栏仅头像 = PC；会话历史抽屉内整行 = 移动端，菜单内容与 PC 一致 */
export type UserPopMenuVariant = "rail" | "drawer";

export interface UserPopMenuProps {
    variant?: UserPopMenuVariant;
}

/** 抽屉内：内联菜单，盖住头像行且不超出侧栏宽度（不用 Portal） */
function UserPopMenuDrawer() {
    const [menuOpen, setMenuOpen] = useState(false);
    const [langOpen, setLangOpen] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);

    const { user, logout } = useAuthContext();
    const { unreadCount, refreshCount } = useNotificationCount();
    const localize = useLocalize();
    const [langcode, setLangcode] = useRecoilState(store.lang);
    const changeLang = (lang: string) => {
        setLangcode(lang);
        setLangOpen(false);
    };
    const displayName = user?.username || "admin";
    const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");
    const [accountDialogOpen, setAccountDialogOpen] = useState(false);
    const [notificationsDialogOpen, setNotificationsDialogOpen] = useState(false);

    const handleAccountInfoClick = () => {
        setAccountDialogOpen(true);
        setMenuOpen(false);
    };

    const handleNotificationsClick = () => {
        setNotificationsDialogOpen(true);
        setMenuOpen(false);
    };

    const handleNotificationsClose = (open: boolean) => {
        setNotificationsDialogOpen(open);
        if (!open) {
            refreshCount();
        }
    };

    const displayUnreadCount = unreadCount > 99 ? "99+" : String(unreadCount);

    useEffect(() => {
        if (!menuOpen) {
            setLangOpen(false);
            return;
        }
        void refreshCount();
        const onPointerDown = (e: PointerEvent) => {
            const el = rootRef.current;
            if (el && !el.contains(e.target as Node)) {
                setMenuOpen(false);
            }
        };
        document.addEventListener("pointerdown", onPointerDown, true);
        return () => document.removeEventListener("pointerdown", onPointerDown, true);
    }, [menuOpen, refreshCount]);

    useEffect(() => {
        if (!menuOpen) return;
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") setMenuOpen(false);
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [menuOpen]);

    const avatarInner =
        avatarUrl ? (
            <AvatarImage src={avatarUrl} alt="User" />
        ) : user?.avatar ? (
            <AvatarImage src={user.avatar} alt="User" />
        ) : (
            <AvatarName name={user?.username} />
        );

    const unreadDot = unreadCount > 0 && (
        <div className="absolute -top-0.5 -right-0.5 z-20 size-2.5 bg-[#f53f3f] rounded-full ring-2 ring-white pointer-events-none" />
    );

    return (
        <div ref={rootRef} className="relative w-full">
            <button
                type="button"
                aria-expanded={menuOpen}
                className={cn(
                    "relative z-10 flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left outline-none",
                    "hover:bg-[#f7f8fa] transition-colors active:scale-[0.99]",
                    // 打开时透明但保留命中区域，避免 pointer-events-none 导致点击穿透到下层
                    menuOpen && "opacity-0",
                )}
                onClick={() => setMenuOpen((open) => !open)}
            >
                <div className="relative shrink-0">
                    <Avatar className="size-9 border border-[#f2f3f5]">{avatarInner}</Avatar>
                    {unreadDot}
                </div>
                <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium text-[#1d2129] truncate">{displayName}</p>
                </div>
                <ChevronRight className="size-4 shrink-0 text-[#86909c]" aria-hidden />
            </button>

            {menuOpen ? (
                <div
                    role="menu"
                    className="absolute bottom-0 left-0 right-0 z-[70] max-w-full rounded-2xl border border-[#f0f0f0] bg-white p-2 shadow-[0_4px_20px_rgba(0,0,0,0.08)]"
                >
                    <div className="flex min-w-0 items-center gap-3 px-3 py-1">
                        <button
                            type="button"
                            className="flex min-w-0 flex-1 items-center gap-3 rounded-lg text-left outline-none"
                            onClick={handleAccountInfoClick}
                        >
                            <Avatar className="size-10 shrink-0 border border-gray-100">{avatarInner}</Avatar>
                            <span className="min-w-0 truncate text-[15px] font-medium text-gray-900">
                                {displayName}
                                <span className="font-normal text-[#86909c]">
                                    {localize("com_nav_profile_username_suffix")}
                                </span>
                            </span>
                        </button>
                    </div>

                    <div className="mx-3 my-1 h-px bg-gray-100" />

                    <button
                        type="button"
                        className="group flex w-full items-center justify-between rounded-xl px-3 py-1.5 text-left outline-none hover:bg-gray-50"
                        onClick={handleNotificationsClick}
                    >
                        <div className="flex items-center gap-3">
                            <Bell className="size-[18px] text-gray-600" />
                            <span className="text-[14px] text-gray-700">{localize("com_notifications_title")}</span>
                        </div>
                        {unreadCount > 0 && (
                            <span className="shrink-0 bg-[#f53f3f] px-2.5 py-0.5 text-center text-[14px] font-medium text-white rounded-full min-w-[24px]">
                                {displayUnreadCount}
                            </span>
                        )}
                    </button>

                    <div className="mt-0.5">
                        <button
                            type="button"
                            className="flex w-full items-center justify-between rounded-xl px-3 py-1.5 text-left outline-none hover:bg-gray-50"
                            onClick={() => setLangOpen((o) => !o)}
                        >
                            <div className="flex items-center gap-3">
                                <Globe className="size-[18px] text-gray-600" />
                                <span className="text-[14px] text-gray-700">{localize("com_nav_language")}</span>
                            </div>
                            <ChevronRight
                                className={cn("size-4 shrink-0 text-gray-500 transition-transform", langOpen && "rotate-90")}
                                aria-hidden
                            />
                        </button>
                        {langOpen ? (
                            <div className="mt-1 space-y-0.5 border-l-2 border-gray-100 py-1 pl-3 ml-3">
                                <button
                                    type="button"
                                    className="flex w-full items-center rounded-lg py-2 pl-2 pr-3 text-left text-sm hover:bg-gray-50"
                                    onClick={() => changeLang("zh-Hans")}
                                >
                                    <span className="flex-1">中文</span>
                                    {langcode === "zh-Hans" && <Check className="size-4 text-blue-600" />}
                                </button>
                                <button
                                    type="button"
                                    className="flex w-full items-center rounded-lg py-2 pl-2 pr-3 text-left text-sm hover:bg-gray-50"
                                    onClick={() => changeLang("en")}
                                >
                                    <span className="flex-1">English</span>
                                    {langcode === "en" && <Check className="size-4 text-blue-600" />}
                                </button>
                                <button
                                    type="button"
                                    className="flex w-full items-center rounded-lg py-2 pl-2 pr-3 text-left text-sm hover:bg-gray-50"
                                    onClick={() => changeLang("ja")}
                                >
                                    <span className="flex-1">日本語</span>
                                    {langcode === "ja" && <Check className="size-4 text-blue-600" />}
                                </button>
                            </div>
                        ) : null}
                    </div>

                    <button
                        type="button"
                        className="mt-1 flex w-full items-center gap-3 rounded-xl px-3 py-1.5 text-left outline-none transition-colors hover:bg-red-50 text-[#f53f3f]"
                        onClick={() => {
                            setMenuOpen(false);
                            logout();
                        }}
                    >
                        <LogOut className="size-[18px]" />
                        <span className="text-[14px] font-medium">{localize("com_nav_log_out")}</span>
                    </button>
                </div>
            ) : null}

            <AccountInfoDialog
                open={accountDialogOpen}
                onOpenChange={setAccountDialogOpen}
                username={displayName}
                avatarUrl={avatarUrl || user?.avatar || ""}
                onAvatarUpdated={(url) => setAvatarUrl(url)}
            />

            <NotificationsDialog
                open={notificationsDialogOpen}
                onOpenChange={handleNotificationsClose}
            />
        </div>
    );
}

function UserPopMenuRail() {
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [accountDialogOpen, setAccountDialogOpen] = useState(false);
    const [notificationsDialogOpen, setNotificationsDialogOpen] = useState(false);

    const { user, logout } = useAuthContext();
    const { unreadCount, refreshCount } = useNotificationCount();

    const localize = useLocalize();
    const [langcode, setLangcode] = useRecoilState(store.lang);
    const changeLang = (lang: string) => setLangcode(lang);
    const displayName = user?.username || "admin";
    const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");

    const handleAccountInfoClick = () => {
        setAccountDialogOpen(true);
    };

    const handleNotificationsClick = () => {
        setNotificationsDialogOpen(true);
    };

    const handleNotificationsClose = (open: boolean) => {
        setNotificationsDialogOpen(open);
        if (!open) {
            refreshCount();
        }
    };

    const displayUnreadCount = unreadCount > 99 ? "99+" : String(unreadCount);
    const handleDropdownOpenChange = (nextOpen: boolean) => {
        setDropdownOpen(nextOpen);
        void refreshCount();
    };

    const avatarInner =
        avatarUrl ? (
            <AvatarImage src={avatarUrl} alt="User" />
        ) : user?.avatar ? (
            <AvatarImage src={user.avatar} alt="User" />
        ) : (
            <AvatarName name={user?.username} />
        );

    const unreadDot = unreadCount > 0 && (
        <div className="absolute -top-0.5 -right-0.5 z-20 size-2.5 bg-[#f53f3f] rounded-full ring-2 ring-white pointer-events-none" />
    );

    return (
        <>
            <DropdownMenu open={dropdownOpen} onOpenChange={handleDropdownOpenChange}>
                <DropdownMenuTrigger asChild>
                    <div className="relative size-10 cursor-pointer outline-none active:scale-95 transition-transform">
                        <Avatar className="size-10 hover:opacity-90 transition-opacity">{avatarInner}</Avatar>
                        {unreadDot}
                    </div>
                </DropdownMenuTrigger>

                <DropdownMenuContent
                    side="top"
                    align="start"
                    sideOffset={14}
                    collisionPadding={12}
                    className="w-[200px] p-2 rounded-2xl shadow-[0_4px_20px_rgba(0,0,0,0.08)] bg-white border-[#f0f0f0]"
                >
                    <div className="flex items-center gap-3 px-3 py-1">
                        <Avatar className="size-10 border border-gray-100" onClick={handleAccountInfoClick}>
                            {avatarInner}
                        </Avatar>
                        <div className="flex flex-col justify-center overflow-hidden" onClick={handleAccountInfoClick}>
                            <span className="text-[15px] font-medium text-gray-900 truncate">{displayName}</span>
                        </div>
                    </div>

                    <div className="h-px bg-gray-100 mx-3 my-1" />

                    <DropdownMenuItem
                        className="group flex items-center justify-between px-3 py-1.5 cursor-pointer rounded-xl hover:bg-gray-50 focus:bg-gray-50 outline-none"
                        onClick={handleNotificationsClick}
                    >
                        <div className="flex items-center gap-3">
                            <Bell className="size-[18px] text-gray-600" />
                            <span className="text-[14px] text-gray-700">{localize("com_notifications_title")}</span>
                        </div>
                        {unreadCount > 0 && (
                            <span className="bg-[#f53f3f] text-white text-[16px] font-medium px-2.5 -py-1 rounded-full min-w-[24px] text-center">
                                {displayUnreadCount}
                            </span>
                        )}
                    </DropdownMenuItem>

                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger className="flex items-center justify-between px-3 py-1.5 cursor-pointer rounded-xl hover:bg-gray-50 focus:bg-gray-50 outline-none">
                            <div className="flex items-center gap-3">
                                <Globe className="size-[18px] text-gray-600" />
                                <span className="text-[14px] text-gray-700">{localize('com_nav_language')}</span>
                            </div>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="rounded-xl border-gray-100 shadow-lg ml-2">
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={() => changeLang('zh-Hans')}>
                                <span className="flex-1 text-sm">中文</span>
                                {langcode === 'zh-Hans' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={() => changeLang('en')}>
                                <span className="flex-1 text-sm">English</span>
                                {langcode === 'en' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={() => changeLang('ja')}>
                                <span className="flex-1 text-sm">日本語</span>
                                {langcode === 'ja' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>

                    <DropdownMenuItem
                        onClick={logout}
                        className="group flex items-center gap-3 px-3 py-1.5 cursor-pointer rounded-xl hover:bg-red-50 focus:bg-red-50 outline-none mt-1 transition-colors !text-[#f53f3f] hover:!text-[#f53f3f] focus:!text-[#f53f3f]"
                    >
                        <LogOut className="size-[18px]" />
                        <span className="text-[14px] font-medium">{localize('com_nav_log_out')}</span>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            <AccountInfoDialog
                open={accountDialogOpen}
                onOpenChange={setAccountDialogOpen}
                username={displayName}
                avatarUrl={avatarUrl || user?.avatar || ""}
                onAvatarUpdated={(url) => setAvatarUrl(url)}
            />

            <NotificationsDialog
                open={notificationsDialogOpen}
                onOpenChange={handleNotificationsClose}
            />
        </>
    );
}

export function UserPopMenu({ variant = "rail" }: UserPopMenuProps) {
    if (variant === "drawer") {
        return <UserPopMenuDrawer />;
    }
    return <UserPopMenuRail />;
}
