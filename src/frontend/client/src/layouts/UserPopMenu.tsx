import { Bell, Globe, LogOut, ChevronRight, User, Check } from "lucide-react";
import { useState } from "react";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/avatar";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    DropdownMenuSub,
    DropdownMenuSubTrigger,
    DropdownMenuSubContent
} from "~/components/ui/DropdownMenu"; // 确保路径正确
import { AccountInfoDialog } from "~/components/AccountInfoDialog";
import { NotificationsDialog } from "~/components/NotificationsDialog";
import { useNotificationCount } from "~/hooks/useNotificationCount";
import { useAuthContext } from "~/hooks";

export function UserPopMenu() {
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [accountDialogOpen, setAccountDialogOpen] = useState(false);
    const [notificationsDialogOpen, setNotificationsDialogOpen] = useState(false);

    // 假设这些来自你的状态管理或 Hook
    const { user, logout } = useAuthContext();
    const { unreadCount, refreshCount } = useNotificationCount();

    // 模拟语言和翻译函数，实际应从你的 i18n hook 中获取
    const langcode = 'zh-Hans';
    const localize = (key: string) => key === 'com_nav_language' ? '语言切换' : '退出登录';
    const changeLang = (lang: string) => console.log("Change to", lang);
    const displayName = user?.username || "admin";

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

    return (
        <>
            <DropdownMenu open={dropdownOpen} onOpenChange={setDropdownOpen}>
                <DropdownMenuTrigger asChild>
                    <div className="relative cursor-pointer outline-none active:scale-95 transition-transform">
                        <Avatar className="size-10 hover:opacity-90 transition-opacity">
                            {user?.avatar ? <AvatarImage src={user?.avatar} alt="User" /> : <AvatarName name={user?.username} />}
                        </Avatar>
                        {/* 头像右上角红点 */}
                        {unreadCount > 0 && (
                            <div className="absolute -top-0.5 -right-0.5 size-2.5 bg-[#f53f3f] rounded-full border-2 border-white" />
                        )}
                    </div>
                </DropdownMenuTrigger>

                <DropdownMenuContent
                    side="right"
                    align="end"
                    className="w-[240px] ml-3 p-2 rounded-2xl shadow-[0_4px_20px_rgba(0,0,0,0.08)] bg-white border-[#f0f0f0]"
                >
                    {/* 1. 用户头部信息 */}
                    <div className="flex items-center gap-3 px-3 py-3">
                        <Avatar className="size-10 border border-gray-100" onClick={handleAccountInfoClick}>
                            {user?.avatar ? <AvatarImage src={user.avatar} alt="User" /> : <AvatarName name={user?.username} />}
                        </Avatar>
                        <div className="flex flex-col justify-center overflow-hidden" onClick={handleAccountInfoClick}>
                            <span className="text-[15px] font-medium text-gray-900 truncate">
                                {displayName}
                            </span>
                        </div>
                    </div>

                    <div className="h-px bg-gray-100 mx-3 my-1" />

                    {/* 3. 消息提醒 (保留逻辑) */}
                    <DropdownMenuItem
                        className="group flex items-center justify-between px-3 py-3 cursor-pointer rounded-xl hover:bg-gray-50 focus:bg-gray-50 outline-none"
                        onClick={handleNotificationsClick}
                    >
                        <div className="flex items-center gap-3">
                            <Bell className="size-[18px] text-gray-600" />
                            <span className="text-[15px] text-gray-700">消息提醒</span>
                        </div>
                        {unreadCount > 0 && (
                            <span className="bg-[#f53f3f] text-white text-[11px] font-medium px-2 py-0.5 rounded-full min-w-[24px] text-center">
                                {unreadCount}
                            </span>
                        )}
                    </DropdownMenuItem>

                    {/* 4. 语言切换 */}
                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger className="flex items-center justify-between px-3 py-3 cursor-pointer rounded-xl hover:bg-gray-50 focus:bg-gray-50 outline-none">
                            <div className="flex items-center gap-3">
                                <Globe className="size-[18px] text-gray-600" />
                                <span className="text-[15px] text-gray-700">{localize('com_nav_language')}</span>
                            </div>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className="rounded-xl border-gray-100 shadow-lg ml-2">
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={() => changeLang('zh-Hans')}>
                                <span className="flex-1 text-sm">中文</span>
                                {langcode === 'zh-Hans' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={() => changeLang('en-US')}>
                                <span className="flex-1 text-sm">English</span>
                                {langcode === 'en-US' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                            <DropdownMenuItem className="py-2.5 px-3 rounded-lg" onClick={() => changeLang('ja')}>
                                <span className="flex-1 text-sm">日本語</span>
                                {langcode === 'ja' && <Check className="ml-2 size-4 text-blue-600" />}
                            </DropdownMenuItem>
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>

                    {/* 5. 退出登录 */}
                    <DropdownMenuItem
                        onClick={logout}
                        className="group flex items-center gap-3 px-3 py-3 cursor-pointer rounded-xl hover:bg-red-50 focus:bg-red-50 outline-none text-[#f53f3f] mt-1 transition-colors"
                    >
                        <LogOut className="size-[18px]" />
                        <span className="text-[15px] font-medium">{localize('com_nav_log_out')}</span>
                    </DropdownMenuItem>
                </DropdownMenuContent>
            </DropdownMenu>

            {/* 弹窗逻辑保持不变 */}
            <AccountInfoDialog
                open={accountDialogOpen}
                onOpenChange={setAccountDialogOpen}
                username={displayName}
                avatarUrl={user?.avatar || ""}
            />

            <NotificationsDialog
                open={notificationsDialogOpen}
                onOpenChange={handleNotificationsClose}
            />
        </>
    );
}