import { AppWindow, BookOpen, HardDrive, LayoutDashboard, MoonIcon, Puzzle, Settings, SunIcon } from "lucide-react";
import { useContext } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import Logo from "../assets/logo.jpeg";
import { Separator } from "../components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import { darkContext } from "../contexts/darkContext";

export default function MainLayout() {
    const { dark, setDark } = useContext(darkContext);
    // const _location = useLocation()

    // 角色
    const localUserStr = localStorage.getItem('auth')
    const localUser = localUserStr ? JSON.parse(atob(localUserStr)) : { name: '', role: '', time: Date.now() }

    return <div className="flex">
        <div className="bg-white h-screen w-36 px-4 py-8 shadow-xl dark:shadow-slate-700 relative">
            <Link className="flex items-center gap-2 text-white font-bold text-xl hover:text-gray-500 text-center" to='/skills'><img src={Logo} className="w-5 h-5" alt="" />文擎毕昇</Link>
            {localUser.role === 'admin' ?
                <nav className="mt-8">
                    <NavLink to='/' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                        <AppWindow /><span className="mx-3">应 用</span>
                    </NavLink>
                    <NavLink to='/skills' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                        <LayoutDashboard /><span className="mx-3">技 能</span>
                    </NavLink>
                    <NavLink to='/filelib' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                        <HardDrive /><span className="mx-3">知 识</span>
                    </NavLink>
                    <a className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full text-gray-200 dark:text-gray-700">
                        <Puzzle /><span className="mx-3">模 型</span>
                    </a>
                    <a className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full text-gray-200 dark:text-gray-700">
                        <Settings /><span className="mx-3">系 统</span>
                    </a>
                </nav> :
                <nav className="mt-8">
                    <NavLink to='/' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                        <AppWindow /><span className="mx-3">应 用</span>
                    </NavLink>
                </nav>}
            <div className="absolute left-0 bottom-0 w-full p-2">
                <Separator />
                <div className="flex h-5 items-center mt-2">
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
                            <TooltipContent><p>主题切换</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                    <Separator className=" mx-2" orientation="vertical" />
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger className="flex-1 py-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                <Link to={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                                    <BookOpen className="side-bar-button-size mx-auto" />
                                </Link>
                            </TooltipTrigger>
                            <TooltipContent><p>文档</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>
        </div>
        <div className="flex-1">
            <Outlet />
        </div>
    </div>
};
