import { Bell, Globe, LogOut, Check } from "lucide-react";
import { useLayoutEffect, useRef, useState, type MouseEvent } from "react";
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

export function UserPopMenu() {
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [menuAlignOffset, setMenuAlignOffset] = useState(0);
    const [menuSideOffset, setMenuSideOffset] = useState(0);
    const triggerRef = useRef<HTMLDivElement>(null);
    const [accountDialogOpen, setAccountDialogOpen] = useState(false);
    const [notificationsDialogOpen, setNotificationsDialogOpen] = useState(false);

    // 假设这些来自你的状态管理或 Hook
    const { user, logout } = useAuthContext();
    const { unreadCount, refreshCount } = useNotificationCount();

    // i18n: read current language from Recoil, provide localize + changeLang
    const localize = useLocalize();
    const [langcode, setLangcode] = useRecoilState(store.lang);
    const changeLang = (lang: string) => setLangcode(lang);
    const displayName = user?.username || "admin";
    const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");
    /** 避免打开瞬间菜单盖住头像时，同一套 pointer 事件的 click 落到下方菜单项（如退出登录） */
    const suppressMenuItemClicksRef = useRef(false);

    // 保留原有方法
    const handleAccountInfoClick = () => {
        setAccountDialogOpen(true);
        // DropdownMenuItem 点击后会自动关闭菜单，无需手动 setDropdownOpen(false)
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
        if (nextOpen) {
            suppressMenuItemClicksRef.current = true;
            window.setTimeout(() => {
                suppressMenuItemClicksRef.current = false;
            }, 150);
        } else {
            suppressMenuItemClicksRef.current = false;
        }
        // Open/close menu时都主动刷新一次未读计数
        void refreshCount();
    };

    /** MenuItem 的 onClick 与 Radix 的 handleSelect 组合：必须 preventDefault 才能阻止误触后的选中与关菜单 */
    const runMenuAction = (fn: () => void) => (e: MouseEvent) => {
        if (suppressMenuItemClicksRef.current) {
            e.preventDefault();
            return;
        }
        fn();
    };

    useLayoutEffect(() => {
        if (!dropdownOpen) {
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
    }, [dropdownOpen]);

    return (
        <>
            <DropdownMenu open={dropdownOpen} onOpenChange={handleDropdownOpenChange}>
                <DropdownMenuTrigger asChild>
                    <div
                        ref={triggerRef}
                        className="relative size-10 cursor-pointer outline-none active:scale-95 transition-transform"
                    >
                        <Avatar className="size-10 hover:opacity-90 transition-opacity">
                            {avatarUrl ? (
                                <AvatarImage src={avatarUrl} alt="User" />
                            ) : user?.avatar ? (
                                <AvatarImage src={user.avatar} alt="User" />
                            ) : (
                                <AvatarName name={user?.username} />
                            )}
                        </Avatar>
                        {/* 头像右上角红点 */}
                        {unreadCount > 0 && (
                            <div className="absolute -top-0.5 -right-0.5 z-20 size-2.5 bg-[#f53f3f] rounded-full ring-2 ring-white pointer-events-none" />
                        )}
                    </div>
                </DropdownMenuTrigger>

                <DropdownMenuContent
                    side="top"
                    align="start"
                    alignOffset={menuAlignOffset}
                    sideOffset={menuSideOffset}
                    collisionPadding={8}
                    onCloseAutoFocus={(e) => e.preventDefault()}
                    className="w-[200px] p-2 rounded-2xl shadow-[0_4px_20px_rgba(0,0,0,0.08)] bg-white border-[#f0f0f0]"
                >
                    {/* 1. 用户头部信息 */}
                    <div className="flex items-center gap-3 px-3 py-1">
                        <Avatar className="size-10 border border-gray-100" onClick={runMenuAction(handleAccountInfoClick)}>
                            {avatarUrl ? (
                                <AvatarImage src={avatarUrl} alt="User" />
                            ) : user?.avatar ? (
                                <AvatarImage src={user.avatar} alt="User" />
                            ) : (
                                <AvatarName name={user?.username} />
                            )}
                        </Avatar>
                        <div className="flex flex-col justify-center overflow-hidden" onClick={runMenuAction(handleAccountInfoClick)}>
                            <span className="text-[15px] font-medium text-gray-900 truncate">
                                {displayName}
                            </span>
                        </div>
                    </div>

                    <div className="h-px bg-gray-100 mx-3 my-1" />

                    {/* 3. 消息提醒 (保留逻辑) */}
                    <DropdownMenuItem
                        className="group flex items-center justify-between px-3 py-1.5 font-normal cursor-pointer rounded-xl hover:bg-gray-50 focus:bg-gray-50 outline-none"
                        onClick={runMenuAction(handleNotificationsClick)}
                    >
                        <div className="flex items-center gap-3">
                            <Bell className="size-[18px] text-gray-600" />
                            <span className="text-[14px] font-normal text-gray-700">{localize("com_notifications_title")}</span>
                        </div>
                        {unreadCount > 0 && (
                            <span className="min-w-[24px] rounded-full bg-[#f53f3f] px-2.5 text-center text-[12px] font-normal text-white leading-none tabular-nums flex h-5 items-center justify-center">
                                {displayUnreadCount}
                            </span>
                        )}
                    </DropdownMenuItem>

                    {/* 4. 语言切换 */}
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger className="flex items-center justify-between px-3 py-1.5 font-normal cursor-pointer rounded-xl hover:bg-gray-50 focus:bg-gray-50 outline-none">
                            <div className="flex items-center gap-3">
                                <Globe className="size-[18px] text-gray-600" />
                                <span className="text-[14px] font-normal text-gray-700">{localize('com_nav_language')}</span>
                            </div>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="rounded-xl border-gray-100 shadow-lg ml-2">
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={runMenuAction(() => changeLang('zh-Hans'))}>
                                <span className="flex-1 text-sm">中文</span>
                                {langcode === 'zh-Hans' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={runMenuAction(() => changeLang('en'))}>
                                <span className="flex-1 text-sm">English</span>
                                {langcode === 'en' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={runMenuAction(() => changeLang('ja'))}>
                                <span className="flex-1 text-sm">日本語</span>
                                {langcode === 'ja' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>

                    {/* 5. 退出登录 */}
                    <DropdownMenuItem
                        onClick={runMenuAction(logout)}
                        className="group flex items-center gap-3 px-3 py-1.5 font-normal cursor-pointer rounded-xl hover:bg-red-50 focus:bg-red-50 outline-none mt-1 transition-colors !text-[#f53f3f] hover:!text-[#f53f3f] focus:!text-[#f53f3f]"
                    >
                        <LogOut className="size-[18px]" />
                        <span className="text-[14px] font-normal">{localize('com_nav_log_out')}</span>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            {/* 弹窗逻辑保持不变 */}
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