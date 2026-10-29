import { HeaderTenantScope } from "@/components/HeaderTenantScope";
// @ts-strict-ignore
import { Button, Dropdown, DropdownChevron, DropdownItem, DropdownSeparator, Select } from '@bisheng/ui';
import { LoadingIcon } from "@/components/bs-icons/loading";

import { GithubIcon } from "@/components/bs-icons";
import { Outlined } from "bisheng-icons";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { locationContext } from "@/contexts/locationContext";
import i18next from "i18next";
import { GanttChartIcon, Lock, MoonStar, Sun } from "lucide-react";

import { useDshBrowserConfig } from "@/hooks/useDshBrowserConfig";
import { Tooltip, TooltipProvider } from "@bisheng/ui";
import { Suspense, useContext, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Separator } from "../components/bs-ui/separator";
import { darkContext } from "../contexts/darkContext";
import { userContext } from "../contexts/userContext";
import { logoutApi } from "../controllers/API/user";
import { User } from "../types/api/user";
import { getBrandAssetUrl } from "../utils/brand";
import { HeaderMenu } from "./HeaderMenu";
import { LicenseBanner } from "./LicenseBanner";

const PRIMARY_PAGE_PATHS = new Set([
    "/dashboard",
    "/build/client",
    "/filelib",
    "/dataset",
    "/model/management",
    "/model/finetune",
    "/dsh",
    "/evaluation",
    "/label",
    "/log",
    "/approval",
    "/sys",
    "/tenant",
]);

export default function MainLayout() {
    const { dark, setDark } = useContext(darkContext);
    const { appConfig } = useContext(locationContext);

    const { user, setUser } = useContext(userContext);
    const { language, options, changLanguage, t } = useLanguage(user);
    const selectLabels = useSelectLabels();
    const languageOptions = Object.entries(options).map(([value, label]) => ({ value, label }));

    const handleLogout = () => {
        bsConfirm({
            title: `${t("prompt")}!`,
            desc: `${t("menu.logoutContent")}？`,
            okTxt: t("system.confirm"),
            onOk(next) {
                return logoutApi().then((_) => {
                    const thirdPartyLogoutUrl = localStorage.getItem("THIRD_PARTY_LOGOUT_URL");
                    localStorage.removeItem("isLogin");
                    if (thirdPartyLogoutUrl) {
                        window.location.href = thirdPartyLogoutUrl;
                    } else {
                        setUser(null);
                    }
                    next();
                });
            },
        });
    };

    // 重置密码
    const navigator = useNavigate();
    const JumpResetPage = () => {
        localStorage.setItem("account", user.external_id || user.user_name);
        navigator("/reset");
    };

    // Global super admins and Child Admins bypass business-menu checks.
    // Department admins receive only the system entry by identity.
    const isSuperAdmin = useMemo(() => user.role === "admin", [user]);
    const isGlobalSuper = Boolean(user.is_global_super);
    const isDeptAdmin = Boolean(user.is_department_admin);
    const isChildAdmin = Boolean(user.is_child_admin);
    const canManageWorkbenchConfig = isSuperAdmin || isChildAdmin;
    const showSystemNav = isSuperAdmin || isDeptAdmin || isChildAdmin;
    const { config: dshConfig } = useDshBrowserConfig();
    const showDshNav = !!dshConfig?.management_enabled && canManageWorkbenchConfig;
    // 审批管理 — 仅超管 / Child Admin（部门管理员不可见）
    const showApprovalNav = isSuperAdmin || isChildAdmin;
    // Admin-area approval scope (falls back to the legacy global flag for
    // roles saved before the workbench/admin split).
    const menuApprovalMode = Boolean(user.menu_approval_mode_admin ?? user.menu_approval_mode);
    const hasAdminEntry =
        isSuperAdmin ||
        isDeptAdmin ||
        isChildAdmin ||
        Boolean(user.web_menu?.includes("admin") || user.web_menu?.includes("backend"));

    const isMenu = (menu: string) => {
        if (menu === "workstation") {
            return (
                user.web_menu?.includes("workstation") ||
                user.web_menu?.includes("frontend") ||
                canManageWorkbenchConfig
            );
        }
        return user.web_menu?.includes(menu) || isSuperAdmin || isChildAdmin;
    };

    // NavLink matches on pathname only, so every link falling back to
    // /menu-pending?menu=<key> would light up together; disambiguate by `menu`.
    const location = useLocation();
    const isPrimaryPage = PRIMARY_PAGE_PATHS.has(location.pathname.replace(/\/$/, ""));
    const pendingNavClass =
        (menuKey: string) =>
        ({ isActive }: { isActive: boolean }) => {
            const otherPendingMenu =
                location.pathname === "/menu-pending" && new URLSearchParams(location.search).get("menu") !== menuKey;
            return `navlink inline-flex rounded-lg w-full px-6 hover:bg-nav-hover h-12 mb-[3.5px]${isActive && !otherPendingMenu ? " active" : ""}`;
        };

    const u = user as User;
    const hasWorkbenchEntry = u.has_workbench ?? isMenu("workstation");

    // Admin-console menus that can be applied for via the approval system.
    // Mirrors MENU_KEY_VALUES in ApprovalPage (top-level admin menus only).
    const APPROVAL_MENUS = new Set(["board", "build", "knowledge", "model", "evaluation", "mark_task", "log"]);

    /** Show if user has permission OR if the menu supports approval requests */
    const showAdminNav = (menu: string) =>
        isMenu(menu) || (menuApprovalMode && hasAdminEntry && APPROVAL_MENUS.has(menu));

    return (
        <div className="flex">
            <div className="bg-[#f8f8f8] dark:bg-background-main w-full h-screen flex flex-col">
                {isGlobalSuper && <LicenseBanner />}
                <div className="flex justify-between h-[64px] shrink-0 bg-[#f8f8f8] dark:bg-background-main relative z-[21]">
                    <div className="flex h-9 my-[14px]">
                        <div className="inline-block">
                            {/* @ts-ignore */}
                            <img
                                src={getBrandAssetUrl("headerLogoLight", "/assets/bisheng/login-logo-small.png")}
                                className="w-[104px] ml-[38px] rounded dark:hidden"
                                alt=""
                            />
                            <img
                                src={getBrandAssetUrl("headerLogoDark", "/assets/bisheng/logo-small-dark.png")}
                                className="w-[104px] ml-[38px] rounded hidden dark:block"
                                alt=""
                            />
                        </div>
                    </div>
                    <div>
                        <HeaderMenu />
                    </div>
                    <div className="flex w-fit relative z-10">
                        {isGlobalSuper && appConfig.multiTenantEnabled && <HeaderTenantScope user={user} />}
                        <div className="flex">
                            <TooltipProvider>
                                <Tooltip
                                    content={
                                        <>
                                            <p>{t("menu.themeSwitch")}</p>
                                        </>
                                    }
                                >
                                    <Button type="button" size="medium" variant="text" iconOnly className="my-4" aria-label={t("menu.themeSwitch")} onClick={() => setDark(!dark)}>
                                        <div className="">
                                            {dark ? (
                                                <Sun className="side-bar-button-size dark:text-slate-50 mx-auto w-[13px] h-[13px]" />
                                            ) : (
                                                <MoonStar className="side-bar-button-size mx-auto w-[17px] h-[17px]" />
                                            )}
                                        </div>
                                    </Button>
                                </Tooltip>
                            </TooltipProvider>
                            <Separator className="mx-[4px] dark:bg-[#111111]" orientation="vertical" />
                            <Select
                                {...selectLabels}
                                variant="ghost"
                                className="my-4 w-auto"
                                aria-label={t("system.language")}
                                options={languageOptions}
                                value={language}
                                onChange={(value) => {
                                    if (value != null) changLanguage(String(value));
                                }}
                            />
                            <Separator
                                className="mx-[23px] h-6 border-l my-5 border-[#dddddd]"
                                orientation="vertical"
                            />
                        </div>
                        <div className="flex items-center h-7 my-4">
                            {/* @ts-ignore */}
                            <img
                                className="h-7 w-7 rounded-2xl mr-4"
                                src={__APP_ENV__.BASE_URL + (user.avatar || "/assets/user.png")}
                                alt=""
                            />
                            <Dropdown
                                trigger="hover"
                                align="end"
                                menu={
                                    <>
                                        {hasWorkbenchEntry && (
                                            <DropdownItem icon={<GanttChartIcon />} onSelect={() => window.open("/workspace/")}>
                                                {t("menu.workspace")}
                                            </DropdownItem>
                                        )}
                                        <DropdownItem icon={<Lock />} onSelect={JumpResetPage}>
                                            {t("menu.changePwd")}
                                        </DropdownItem>
                                        <DropdownSeparator />
                                        <DropdownItem danger icon={<Outlined.LogOut />} onSelect={handleLogout}>
                                            {t("menu.logout")}
                                        </DropdownItem>
                                    </>
                                }
                            >
                                <Button type="button" variant="text" color="default" className="mr-8 max-w-40">
                                    <span className="truncate">{user.user_name}</span>
                                    <DropdownChevron />
                                </Button>
                            </Dropdown>
                        </div>
                    </div>
                </div>
                <div className="flex flex-1 min-h-0">
                    <div className="relative z-10 bg-[#f8f8f8] dark:bg-background-main h-full w-[184px] min-w-[184px] px-3  shadow-x1 flex justify-between text-center ">
                        <nav
                            className="overflow-y-auto overflow-x-hidden [&_.navlink>svg]:text-text-2 [&_.navlink.active>svg]:text-inherit"
                            style={{ maxHeight: "calc(100vh - 64px - 90px - var(--license-banner-h, 0px))" }}
                        >
                            {/* <NavLink to='/' className={`navlink inline-flex rounded-lg w-full px-6 hover:bg-nav-hover h-12 mb-[3.5px]`}>
                            <Outlined.Application className="h-4 w-4 my-4 mr-2 shrink-0" /><span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">{t('menu.app')}</span>
                        </NavLink> */}
                            {showAdminNav("board") && (
                                <>
                                    <NavLink
                                        to={isMenu("board") ? "/dashboard" : "/menu-pending?menu=board"}
                                        className={pendingNavClass("board")}
                                    >
                                        <Outlined.Dashboard className="h-4 w-4 my-4 mr-2 shrink-0" />
                                        <span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">
                                            {t("menu.dashboard")}
                                        </span>
                                    </NavLink>
                                </>
                            )}
                            {(showAdminNav("build") || canManageWorkbenchConfig) && (
                                <NavLink
                                    to={
                                        isMenu("build")
                                            ? "/build"
                                            : canManageWorkbenchConfig
                                              ? "/build/client"
                                              : "/menu-pending?menu=build"
                                    }
                                    className={pendingNavClass("build")}
                                >
                                    <Outlined.Application className="h-4 w-4 my-4 mr-2 shrink-0" />
                                    <span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">
                                        {t("menu.skills")}
                                    </span>
                                </NavLink>
                            )}
                            {showAdminNav("knowledge") && (
                                <NavLink
                                    to={isMenu("knowledge") ? "/filelib" : "/menu-pending?menu=knowledge"}
                                    className={pendingNavClass("knowledge")}
                                >
                                    <Outlined.Books className="h-4 w-4 my-4 mr-2 shrink-0" />
                                    <span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">
                                        {t("menu.knowledge")}
                                    </span>
                                </NavLink>
                            )}
                            {isMenu("dataset") && (
                                <>
                                    <NavLink
                                        to="/dataset"
                                        className={`navlink inline-flex rounded-lg w-full px-6 hover:bg-nav-hover h-12 mb-[3.5px]`}
                                    >
                                        <Outlined.File className="h-4 w-4 my-4 mr-2 shrink-0" />
                                        <span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">
                                            {t("menu.dataset")}
                                        </span>
                                    </NavLink>
                                </>
                            )}
                            {showAdminNav("model") && (
                                <NavLink
                                    to={isMenu("model") ? "/model" : "/menu-pending?menu=model"}
                                    className={pendingNavClass("model")}
                                >
                                    <Outlined.BlocksAndArrows className="h-4 w-4 my-4 mr-2 shrink-0" />
                                    <span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">
                                        {t("menu.models")}
                                    </span>
                                </NavLink>
                            )}
                            {showDshNav && (
                                <NavLink
                                    to="/dsh"
                                    aria-label={t("menu.dshDesktop")}
                                    className={`navlink inline-flex items-center rounded-lg w-full px-6 hover:bg-nav-hover h-12 mb-[3.5px]`}
                                >
                                    <Outlined.DeviceDesktopExchange aria-hidden="true" className="h-4 w-4 mr-2 shrink-0" />
                                    <span
                                        aria-hidden="true"
                                        className="mx-[14px] inline-flex w-[3em] shrink-0 justify-between text-sm"
                                    >
                                        {Array.from(t("menu.dshDesktop")).map((character, index) => (
                                            <span key={index}>{character}</span>
                                        ))}
                                    </span>
                                </NavLink>
                            )}
                            {showAdminNav("evaluation") && (
                                <NavLink
                                    to={isMenu("evaluation") ? "/evaluation" : "/menu-pending?menu=evaluation"}
                                    className={pendingNavClass("evaluation")}
                                >
                                    <Outlined.ListSuccess className="h-4 w-4 my-4 mr-2 shrink-0" />
                                    <span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">
                                        {t("menu.evaluation")}
                                    </span>
                                </NavLink>
                            )}
                            {showAdminNav("mark_task") && (
                                <NavLink
                                    to={isMenu("mark_task") ? "/label" : "/menu-pending?menu=mark_task"}
                                    className={pendingNavClass("mark_task")}
                                >
                                    <Outlined.Edit className="h-4 w-4 my-4 mr-2 shrink-0" />
                                    <span className="mx-[14px] max-w-[48px] text-[14px] leading-[48px]">
                                        {t("menu.annotation")}
                                    </span>
                                </NavLink>
                            )}
                            {showAdminNav("log") && (
                                <NavLink
                                    to={isMenu("log") ? "/log" : "/menu-pending?menu=log"}
                                    className={pendingNavClass("log")}
                                >
                                    <Outlined.History className="h-4 w-4 my-4 mr-2 shrink-0" />
                                    <span className="mx-[14px] max-w-[56px] text-[14px] leading-[48px]">
                                        {t("menu.log")}
                                    </span>
                                </NavLink>
                            )}
                            {showApprovalNav && (
                                <NavLink
                                    to="/approval"
                                    className={`navlink inline-flex rounded-lg w-full px-6 hover:bg-nav-hover h-12 mb-[3.5px]`}
                                >
                                    <Outlined.ApprovalTodo className="h-4 w-4 my-4 mr-2 shrink-0" />
                                    <span className="mx-[14px] max-w-[56px] text-[14px] leading-[48px]">
                                        {t("menu.approval")}
                                    </span>
                                </NavLink>
                            )}
                            {showSystemNav && (
                                <>
                                    <NavLink
                                        to="/sys"
                                        className={`navlink inline-flex rounded-lg w-full px-6 hover:bg-nav-hover h-12 mb-[3.5px]`}
                                    >
                                        <Outlined.Setting className="h-4 w-4 my-4 mr-2 shrink-0" />
                                        <span className="mx-[14px] max-w-[56px] text-[14px] leading-[48px]">
                                            {t("menu.system")}
                                        </span>
                                    </NavLink>
                                </>
                            )}
                            {isSuperAdmin && appConfig.multiTenantEnabled && (
                                <>
                                    <NavLink
                                        to="/tenant"
                                        className={`navlink inline-flex rounded-lg w-full px-6 hover:bg-nav-hover h-12 mb-[3.5px]`}
                                    >
                                        <Outlined.City className="h-4 w-4 my-4 mr-2 shrink-0" />
                                        <span className="mx-[14px] max-w-[56px] text-[14px] leading-[48px]">
                                            {t("tenant.management")}
                                        </span>
                                    </NavLink>
                                </>
                            )}
                        </nav>
                        {!appConfig.noFace && (
                            <div className="absolute left-0 bottom-0 w-[180px] p-2">
                                <div className="help flex items-between my-2">
                                    <TooltipProvider>
                                        <Tooltip
                                            content={
                                                <>
                                                    <p>{t("menu.github")}</p>
                                                </>
                                            }
                                        >
                                            <span
                                                tabIndex={0}
                                                className="h-[72px] w-[78px] cursor-pointer bg-background-tip rounded-lg hover:bg-[#1b1f23] hover:text-[white] transition-all dark:hover:bg-background-tip-darkhover"
                                            >
                                                <Link className="flex h-full w-full flex-col items-center justify-center" to={"https://github.com/dataelement/bisheng"} target="_blank">
                                                    <GithubIcon className="side-bar-button-size mx-auto w-5 h-5 " />
                                                    <span className="block text-[12px] mt-[8px] font-bold">
                                                        {t("menu.github")}
                                                    </span>
                                                </Link>
                                            </span>
                                        </Tooltip>
                                    </TooltipProvider>
                                    <Separator className="mx-1" orientation="vertical" />
                                    <TooltipProvider>
                                        <Tooltip
                                            content={
                                                <>
                                                    <p>{t("menu.document")}</p>
                                                </>
                                            }
                                        >
                                            <span
                                                tabIndex={0}
                                                className="h-[72px] w-[78px] cursor-pointer bg-background-tip rounded-lg p-0 align-top hover:bg-[#0055e3] hover:text-[white]  transition-all"
                                            >
                                                <Link
                                                    className="m-0 flex h-full w-full flex-col items-center justify-center p-0"
                                                    to={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"}
                                                    target="_blank"
                                                >
                                                    <Outlined.BookOpenText className=" mx-auto w-5 h-5" />
                                                    <span className="block text-[12px] mt-[8px] font-bold">
                                                        {t("menu.bookopen")}
                                                    </span>
                                                </Link>
                                            </span>
                                        </Tooltip>
                                    </TooltipProvider>
                                </div>
                            </div>
                        )}
                    </div>
                    {/* Width comes from the flex row, not from 100vw: 100vw counts the
                    document scrollbar, so calc(100vw-184px) overshot the free space
                    by the scrollbar width and forced a horizontal document scrollbar
                    (which then cost vertical space and produced a second, outer scrollbar). */}
                    {/* Clip child backgrounds to the shared radius without creating a scroll container. */}
                    <div className={`flex-1 min-w-0 bg-background-main-content rounded-lg${isPrimaryPage ? " mr-4 mb-4 overflow-clip" : ""}`}>
                        <Suspense
                            fallback={
                                <div className="flex items-center justify-center h-full">
                                    <LoadingIcon />
                                </div>
                            }
                        >
                            <Outlet />
                        </Suspense>
                    </div>
                </div>
            </div>

            {/* // mobile */}
            <div className="fixed w-full h-full top-0 left-0 bg-[rgba(0,0,0,0.4)] sm:hidden text-sm z-50">
                <div className="w-10/12 bg-gray-50 mx-auto mt-[30%] rounded-xl px-4 py-10">
                    <p className=" text-sm text-center">{t("menu.forBestExperience")}</p>
                    {!appConfig.isPro && (
                        <div className="flex mt-8 justify-center gap-4">
                            <a href={"https://github.com/dataelement/bisheng"} target="_blank">
                                <GithubIcon className="side-bar-button-size mx-auto" />
                                Github
                            </a>
                            <a href={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                                <Outlined.BookOpenText className="side-bar-button-size mx-auto" />{" "}
                                {t("menu.onlineDocumentation")}
                            </a>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}

const useLanguage = (user: User) => {
    const { t } = useTranslation();
    // APP_CONFIG.disableJa (config.js) hides Japanese from the switcher.
    const jaDisabled = !!(window as any).APP_CONFIG?.disableJa;
    const options: Record<string, string> = {
        "zh-Hans": t("menu.languageChinese"),
        "en-US": "English",
        ...(!jaDisabled && { ja: t("menu.languageJapanese") }),
    };
    // Source of truth for the displayed label is whatever i18next resolved
    // during init (which already honors disableJa).
    const initialLanguage = options[i18next.language] ? i18next.language : "zh-Hans";
    const [language, setLanguage] = useState(initialLanguage);
    useEffect(() => {
        const lang = user.user_id ? localStorage.getItem("i18nextLng") : null;
        if (lang) {
            const normalized = lang === "zh" ? "zh-Hans" : lang;
            setLanguage(options[normalized] ? normalized : initialLanguage);
        }
    }, [user]);

    const changLanguage = (ln: string) => {
        setLanguage(ln);
        localStorage.setItem("i18nextLng", ln);
        // workspace
        localStorage.removeItem("lang");
        document.cookie = `lang=${ln}; path=/; expires=${new Date(Date.now() + 365 * 24 * 60 * 60 * 1000).toUTCString()}`;
        i18next.changeLanguage(ln);
    };
    return {
        language,
        options,
        changLanguage,
        t,
    };
};
