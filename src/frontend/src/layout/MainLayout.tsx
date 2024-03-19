import i18next from "i18next";
import { AppWindow, BookOpen, Github, Globe, HardDrive, Languages, LayoutDashboard, LogOut, MoonIcon, Puzzle, Settings, SunIcon } from "lucide-react";
import { useContext, useEffect, useState } from "react";
import { ErrorBoundary } from "react-error-boundary";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet } from "react-router-dom";
import CrashErrorComponent from "../components/CrashErrorComponent";
import { Separator } from "../components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import { darkContext } from "../contexts/darkContext";
import { userContext } from "../contexts/userContext";
import { logoutApi } from "../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../controllers/request";
import { User } from "../types/api/user";

export default function MainLayout() {
    const { dark, setDark } = useContext(darkContext);
    // 角色
    const { user, setUser } = useContext(userContext);

    const { language, options, changLanguage, t } = useLanguage(user)

    const handleLogout = () => {
        captureAndAlertRequestErrorHoc(logoutApi()).then(_ => {
            setUser(null)
            localStorage.removeItem('isLogin')
        })
    }

    return <div className="flex">
        <div className="bg-white h-screen w-40 px-4 py-8 shadow-xl dark:shadow-slate-700 relative text-center">
            <Link className="inline-block mb-1" to='/'><img src='/logo.jpeg' className="w-9 h-9" alt="" /></Link>
            <h1 className="text-white font-bold text-xl text-center">{t('title')}</h1>
            <nav className="mt-8">
                <NavLink to='/' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                    <AppWindow /><span className="mx-3 max-w-[48px]">{t('menu.app')}</span>
                </NavLink>
                <NavLink to='/skills' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                    <LayoutDashboard /><span className="mx-3 max-w-[48px]">{t('menu.skills')}</span>
                </NavLink>
                <NavLink to='/filelib' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                    <HardDrive /><span className="mx-3 max-w-[48px]">{t('menu.knowledge')}</span>
                </NavLink>
                <NavLink to='/model' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                    <Puzzle /><span className="mx-3 max-w-[48px]">{t('menu.models')}</span>
                </NavLink>
                {
                    user.role === 'admin' && <>
                        <NavLink to='/sys' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                            <Settings /><span className="mx-3 max-w-[48px]">{t('menu.system')}</span>
                        </NavLink>
                    </>
                }
            </nav>
            <div className="absolute left-0 bottom-0 w-full p-2">
                {/* <Separator /> */}
                <div className="flex h-5 items-center my-2">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger className="flex-1 py-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                <div className="" onClick={() => setDark(!dark)}>
                                    {dark ? (
                                        <SunIcon className="side-bar-button-size mx-auto" />
                                    ) : (
                                        <MoonIcon className="side-bar-button-size mx-auto" />
                                    )}
                                </div>
                            </TooltipTrigger>
                            <TooltipContent><p>{t('menu.themeSwitch')}</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                    <Separator className="mx-1" orientation="vertical" />
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger className="flex-1 py-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                <div className="" onClick={changLanguage}>
                                    {language === 'en'
                                        ? <Languages className="side-bar-button-size mx-auto" />
                                        : <Globe className="side-bar-button-size mx-auto" />}
                                </div>
                            </TooltipTrigger>
                            <TooltipContent><p>{options[language]}</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                    <Separator className="mx-1" orientation="vertical" />
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger className="flex-1 py-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                <Link to={"https://github.com/dataelement/bisheng"} target="_blank">
                                    <Github className="side-bar-button-size mx-auto" />
                                </Link>
                            </TooltipTrigger>
                            <TooltipContent><p>github</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                    <Separator className="mx-1" orientation="vertical" />
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger className="flex-1 py-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                <Link to={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                                    <BookOpen className="side-bar-button-size mx-auto" />
                                </Link>
                            </TooltipTrigger>
                            <TooltipContent><p>{t('menu.document')}</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
                <Separator className="mx-1" />
                <div className="flex h-5 items-center my-2">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger className="flex-1 py-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                <div className=" flex justify-center gap-2 items-center" onClick={handleLogout}>
                                    <LogOut className="side-bar-button-size" />
                                    <span>{t('menu.logout')}</span>
                                </div>
                            </TooltipTrigger>
                            <TooltipContent><p>{t('menu.logoutDescription')}</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>
        </div>
        <div className="flex-1 overflow-hidden">
            <ErrorBoundary
                onReset={() => window.location.href = window.location.href}
                FallbackComponent={CrashErrorComponent}
            >
                <Outlet />
            </ErrorBoundary>
        </div>
        {/* // mobile */}
        <div className="fixed w-full h-full top-0 left-0 bg-[rgba(0,0,0,0.4)] sm:hidden text-sm">
            <div className="w-10/12 bg-gray-50 mx-auto mt-[30%] rounded-xl px-4 py-10">
                <p className=" text-sm text-center">{t('menu.forBestExperience')}</p>
                <div className="flex mt-8 justify-center gap-4">
                    <a href={"https://github.com/dataelement/bisheng"} target="_blank">
                        <Github className="side-bar-button-size mx-auto" />Github
                    </a>
                    <a href={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                        <BookOpen className="side-bar-button-size mx-auto" /> {t('menu.onlineDocumentation')}
                    </a>
                </div>
            </div>
        </div>
    </div>
};

const useLanguage = (user: User) => {
    const [language, setLanguage] = useState('en')
    useEffect(() => {
        const lang = user.user_id ? localStorage.getItem('language-' + user.user_id) : null
        if (lang) {
            setLanguage(lang)
        }
    }, [user])

    const { t } = useTranslation()
    const changLanguage = () => {
        const ln = language === 'zh' ? 'en' : 'zh'
        setLanguage(ln)
        localStorage.setItem('language-' + user.user_id, ln)
        localStorage.setItem('language', ln)
        i18next.changeLanguage(ln)
    }
    return {
        language,
        options: { en: '使用中文', zh: 'English' },
        changLanguage,
        t
    }
}
