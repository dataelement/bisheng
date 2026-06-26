import { Check, ChevronRight } from "lucide-react";
import { Outlined } from "bisheng-icons";
import { useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { useRecoilState } from "recoil";
import { AccountInfoDialog } from "~/components/AccountInfoDialog";
import { NotificationsDialog } from "~/components/NotificationsDialog";
import { ApprovalCenterDialog } from "~/components/approval/ApprovalCenterDialog";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import {
    DropdownMenu,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger
} from "~/components/ui/DropdownMenu";
import {
    ActionMenuContent,
    ActionMenuDivider,
    ActionMenuItem,
    actionMenuItemClassName,
    actionMenuItemIconClassName,
    actionMenuLabelClassName,
    actionMenuSurfaceClassName,
} from "~/components/ActionMenu";
import { useAuthContext, useLocalize } from "~/hooks";
import { useNotificationCount } from "~/hooks/useNotificationCount";
import { useNotificationsFromUrl } from "~/hooks/useNotificationsFromUrl";
import store from "~/store";
import { cn } from "~/utils";

/** 左侧窄栏仅头像 = PC；会话历史抽屉内整行 = 移动端，菜单内容与 PC 一致 */
export type UserPopMenuVariant = "rail" | "drawer";

export interface UserPopMenuProps {
    variant?: UserPopMenuVariant;
}

type ApprovalCenterTarget = {
    tab: "my_tasks" | "my_requests";
    taskId?: number | null;
    instanceId?: number | null;
};

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
    const [approvalDialogOpen, setApprovalDialogOpen] = useState(false);
    const [approvalDialogTarget, setApprovalDialogTarget] = useState<ApprovalCenterTarget>({ tab: "my_tasks" });
    const {
        open: notificationsDialogOpen,
        setOpen: setNotificationsDialogOpen,
        focusedMessageId,
    } = useNotificationsFromUrl();

    const handleAccountInfoClick = () => {
        setAccountDialogOpen(true);
        setMenuOpen(false);
    };

    const handleNotificationsClick = () => {
        setNotificationsDialogOpen(true);
        setMenuOpen(false);
    };

    const openApprovalCenter = (target: ApprovalCenterTarget) => {
        setApprovalDialogTarget(target);
        setApprovalDialogOpen(true);
        setNotificationsDialogOpen(false);
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
                        onClick={() => openApprovalCenter({ tab: "my_tasks" })}
                    >
                        <div className="flex items-center gap-3">
                            <Outlined.Seal className="size-[18px] text-gray-600" />
                            <span className="whitespace-nowrap text-[14px] text-gray-700">{localize("com_approval_center_title")}</span>
                        </div>
                    </button>

                    <button
                        type="button"
                        className="group flex w-full items-center justify-between rounded-xl px-3 py-1.5 text-left outline-none hover:bg-gray-50"
                        onClick={handleNotificationsClick}
                    >
                        <div className="flex items-center gap-3">
                            <Outlined.Bell className="size-[18px] text-gray-600" />
                            <span className="whitespace-nowrap text-[14px] text-gray-700">{localize("com_notifications_title")}</span>
                        </div>
                        {unreadCount > 0 && (
                            <span className="shrink-0 bg-[#f53f3f] px-2.5 py-0.5 text-center text-[12px] font-medium text-white rounded-full min-w-[24px]">
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
                                <Outlined.Earth className="size-[18px] text-gray-600" />
                                <span className="whitespace-nowrap text-[14px] text-gray-700">{localize("com_nav_language")}</span>
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
                                {!window.APP_CONFIG?.disableJa && (
                                    <button
                                        type="button"
                                        className="flex w-full items-center rounded-lg py-2 pl-2 pr-3 text-left text-sm hover:bg-gray-50"
                                        onClick={() => changeLang("ja")}
                                    >
                                        <span className="flex-1">日本語</span>
                                        {langcode === "ja" && <Check className="size-4 text-blue-600" />}
                                    </button>
                                )}
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
                        <Outlined.LogOut className="size-[18px]" />
                        <span className="whitespace-nowrap text-[14px] font-medium">{localize("com_nav_log_out")}</span>
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
                focusedMessageId={focusedMessageId}
                onOpenApprovalCenter={openApprovalCenter}
            />

            <ApprovalCenterDialog
                open={approvalDialogOpen}
                onOpenChange={setApprovalDialogOpen}
                target={approvalDialogTarget}
            />
        </div>
    );
}

function UserPopMenuRail() {
    const [dropdownOpen, setDropdownOpen] = useState(false);
    const [menuAlignOffset, setMenuAlignOffset] = useState(0);
    const [menuSideOffset, setMenuSideOffset] = useState(0);
    const triggerRef = useRef<HTMLDivElement>(null);
    const [accountDialogOpen, setAccountDialogOpen] = useState(false);
    const [approvalDialogOpen, setApprovalDialogOpen] = useState(false);
    const [approvalDialogTarget, setApprovalDialogTarget] = useState<ApprovalCenterTarget>({ tab: "my_tasks" });
    const {
        open: notificationsDialogOpen,
        setOpen: setNotificationsDialogOpen,
        focusedMessageId,
    } = useNotificationsFromUrl();

    const { user, logout } = useAuthContext();
    const { unreadCount, refreshCount } = useNotificationCount();

    const localize = useLocalize();
    const [langcode, setLangcode] = useRecoilState(store.lang);
    const changeLang = (lang: string) => setLangcode(lang);
    const displayName = user?.username || "admin";
    const [avatarUrl, setAvatarUrl] = useState<string>(user?.avatar || "");
    /** 避免打开瞬间菜单盖住头像时，同一套 pointer 事件的 click 落到下方菜单项（如退出登录） */
    const suppressMenuItemClicksRef = useRef(false);

    const handleAccountInfoClick = () => {
        setAccountDialogOpen(true);
    };

    const handleNotificationsClick = () => {
        setNotificationsDialogOpen(true);
    };

    const openApprovalCenter = (target: ApprovalCenterTarget) => {
        setApprovalDialogTarget(target);
        setApprovalDialogOpen(true);
        setDropdownOpen(false);
        setNotificationsDialogOpen(false);
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
            }, 400);
        } else {
            suppressMenuItemClicksRef.current = false;
        }
        // Open/close menu时都主动刷新一次未读计数
        void refreshCount();
    };

    /** 菜单内非 Item 区域（头像、昵称 div）仍用 click */
    const runMenuAction = (fn: () => void) => (e: MouseEvent) => {
        if (suppressMenuItemClicksRef.current) {
            e.preventDefault();
            return;
        }
        fn();
    };

    /**
     * DropdownMenuItem 由 Radix 通过 onSelect 选中，仅用 onClick 无法阻止「打开瞬间同一指针落在退出登录」的误触。
     * 在抑制窗口内必须 event.preventDefault() 才能取消本次选中。
     */
    const runMenuItemSelect = (fn: () => void) => (e: Event) => {
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

                <ActionMenuContent
                    side="top"
                    align="start"
                    width={200}
                    alignOffset={menuAlignOffset}
                    sideOffset={menuSideOffset}
                    collisionPadding={8}
                    onCloseAutoFocus={(e) => e.preventDefault()}
                >
                    {/* User header — opens account info */}
                    <div
                        className={cn(actionMenuItemClassName, "py-1.5 hover:bg-[#f2f3f5]")}
                        onClick={runMenuAction(handleAccountInfoClick)}
                    >
                        <Avatar className="size-7 shrink-0 border border-gray-100">
                            {avatarUrl ? (
                                <AvatarImage src={avatarUrl} alt="User" />
                            ) : user?.avatar ? (
                                <AvatarImage src={user.avatar} alt="User" />
                            ) : (
                                <AvatarName name={user?.username} />
                            )}
                        </Avatar>
                        <span className={cn(actionMenuLabelClassName, "font-medium")}>{displayName}</span>
                    </div>

                    <ActionMenuDivider />

                    {/* 审批中心：合并原「我的待办 / 我的申请」入口，默认进「我的审批」子 tab */}
                    <ActionMenuItem
                        icon={<Outlined.Seal />}
                        label={localize("com_approval_center_title")}
                        onSelect={runMenuItemSelect(() => openApprovalCenter({ tab: "my_tasks" }))}
                    />

                    <ActionMenuItem
                        icon={<Outlined.Bell />}
                        onSelect={runMenuItemSelect(handleNotificationsClick)}
                    >
                        <span className={cn(actionMenuLabelClassName, "flex-1")}>{localize("com_notifications_title")}</span>
                        {unreadCount > 0 && (
                            <span className="ml-auto flex h-5 min-w-[20px] items-center justify-center rounded-full bg-[#f53f3f] px-1.5 text-[12px] leading-none text-white tabular-nums">
                                {displayUnreadCount}
                            </span>
                        )}
                    </ActionMenuItem>

                    <DropdownMenuSub>
                        <DropdownMenuSubTrigger className={cn(actionMenuItemClassName, "font-normal data-[state=open]:bg-[#f2f3f5]")}>
                            <Outlined.Earth className={actionMenuItemIconClassName} />
                            <span className={cn(actionMenuLabelClassName, "flex-1")}>{localize('com_nav_language')}</span>
                        </DropdownMenuSubTrigger>
                        <DropdownMenuSubContent className={cn(actionMenuSurfaceClassName, "z-[100] ml-2 min-w-[140px] gap-0 p-2")}>
                            <ActionMenuItem onSelect={runMenuItemSelect(() => changeLang('zh-Hans'))}>
                                <span className={cn(actionMenuLabelClassName, "flex-1")}>中文</span>
                                {langcode === 'zh-Hans' && <Check className="ml-2 size-4 text-blue-500" />}
                            </ActionMenuItem>
                            <ActionMenuItem onSelect={runMenuItemSelect(() => changeLang('en'))}>
                                <span className={cn(actionMenuLabelClassName, "flex-1")}>English</span>
                                {langcode === 'en' && <Check className="ml-2 size-4 text-blue-500" />}
                            </ActionMenuItem>
                            {!window.APP_CONFIG?.disableJa && (
                                <ActionMenuItem onSelect={runMenuItemSelect(() => changeLang('ja'))}>
                                    <span className={cn(actionMenuLabelClassName, "flex-1")}>日本語</span>
                                    {langcode === 'ja' && <Check className="ml-2 size-4 text-blue-500" />}
                                </ActionMenuItem>
                            )}
                        </DropdownMenuSubContent>
                    </DropdownMenuSub>

                    <ActionMenuItem
                        danger
                        icon={<Outlined.LogOut />}
                        label={localize('com_nav_log_out')}
                        onSelect={runMenuItemSelect(logout)}
                    />
                </ActionMenuContent>
            </DropdownMenu >

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
                focusedMessageId={focusedMessageId}
                onOpenApprovalCenter={openApprovalCenter}
            />

            <ApprovalCenterDialog
                open={approvalDialogOpen}
                onOpenChange={setApprovalDialogOpen}
                target={approvalDialogTarget}
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
