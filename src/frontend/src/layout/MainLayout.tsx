import { AppWindow, BookOpen, Github, HardDrive, LayoutDashboard, LogOut, MoonIcon, Puzzle, Settings, SunIcon } from "lucide-react";
import { useContext } from "react";
import { Link, NavLink, Outlet } from "react-router-dom";
import Logo from "../assets/logo.jpeg";
import { Separator } from "../components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import { darkContext } from "../contexts/darkContext";
import { userContext } from "../contexts/userContext";

export default function MainLayout() {
    const { dark, setDark } = useContext(darkContext);
    // const _location = useLocation()

    // 角色
    const { user, setUser } = useContext(userContext);

    return <div className="flex">
        <div className="bg-white h-screen w-40 px-4 py-8 shadow-xl dark:shadow-slate-700 relative text-center">
            <Link className="inline-block mb-1" to='/'><img src={Logo} className="w-9 h-9" alt="" /></Link>
            <h1 className="text-white font-bold text-xl text-center">文擎毕昇</h1>

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
                <NavLink to='/model' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                    <Puzzle /><span className="mx-3">模 型</span>
                </NavLink>
                {
                    user.role === 'admin' && <>
                        <NavLink to='/sys' className="navlink inline-flex rounded-md text-sm px-4 py-2 mt-1 w-full hover:bg-secondary/80">
                            <Settings /><span className="mx-3">系 统</span>
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
                            <TooltipContent><p>主题切换</p></TooltipContent>
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
                            <TooltipContent><p>文档</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
                <Separator className="mx-1" />
                <div className="flex h-5 items-center my-2">
                    <TooltipProvider>
                        <Tooltip>
                            <TooltipTrigger className="flex-1 py-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                <div className=" flex justify-center gap-2 items-center" onClick={() => { setUser(null); localStorage.setItem('UUR_INFO', '') }}>
                                    <LogOut className="side-bar-button-size" />
                                    <span>退出</span>
                                </div>
                            </TooltipTrigger>
                            <TooltipContent><p>退出登录</p></TooltipContent>
                        </Tooltip>
                    </TooltipProvider>
                </div>
            </div>
        </div>
        <div className="flex-1">
            <Outlet />
        </div>
        {/* // mobile */}
        <div className="fixed w-full h-full top-0 left-0 bg-[rgba(0,0,0,0.4)] sm:hidden text-sm">
            <div className="w-10/12 bg-gray-50 mx-auto mt-[30%] rounded-xl px-4 py-10">
                <p className=" text-sm text-center">为了您的良好体验，请在 PC 端访问该网站</p>
                <div className="flex mt-8 justify-center gap-4">
                    <a href={"https://github.com/dataelement/bisheng"} target="_blank">
                        <Github className="side-bar-button-size mx-auto" />Github
                    </a>
                    <a href={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                        <BookOpen className="side-bar-button-size mx-auto" /> 在线文档
                    </a>
                </div>
            </div>
        </div>
    </div>
};
