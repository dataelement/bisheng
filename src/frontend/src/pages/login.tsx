import { BookOpen, Github } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import Logo from "../assets/logo.jpeg";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Separator } from "../components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import { alertContext } from "../contexts/alertContext";
import { userContext } from "../contexts/userContext";
import { loginApi, registerApi } from "../controllers/API";
import StarBg from "./starBg";

export const LoginPage = () => {
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const { setUser } = useContext(userContext);

    const isLoading = false

    const mailRef = useRef(null)
    const pwdRef = useRef(null)
    const agenPwdRef = useRef(null)

    // login or register
    const [showLogin, setShowLogin] = useState(true)

    const handleLogin = () => {
        const error = []
        const [mail, pwd] = [mailRef.current.value, pwdRef.current.value]
        if (!mail) error.push('请填写账号')
        if (!pwd) error.push('请填写密码')
        if (error.length) return setErrorData({
            title: "提示: ",
            list: error,
        });
        loginApi(mail, pwd).then(res => {
            // setUser(res.data)
            localStorage.setItem('UUR_INFO', btoa(JSON.stringify(res.data)))
            location.href = '/'
        }).catch(e => {
            console.error(e.response.data.detail);
            setErrorData({
                title: "提示: ",
                list: [e.response.data.detail],
            });
        })
    }

    const handleRegister = () => {
        const error = []
        const [mail, pwd, apwd] = [mailRef.current.value, pwdRef.current.value, agenPwdRef.current.value]
        if (!mail) error.push('请填写账号')
        if (mail.length < 3) error.push('账号过短')
        if (!/.{6,}/.test(pwd)) error.push('请填写密码,至少六位')
        if (pwd !== apwd) error.push('两次密码不一致')
        if (error.length) return setErrorData({
            title: "提示: ",
            list: error,
        });
        registerApi(mail, pwd).then(res => {
            setSuccessData({ title: '注册成功,请输入密码进行登录' })
            pwdRef.current.value = ''
            setShowLogin(true)
        }).catch(err => {
            console.error(err.response.data.detail);
            setErrorData({
                title: "提示: ",
                list: [err.response.data.detail],
            });
        })
    }

    useEffect(() => {
        console.log(
			"%cBiSheng 0.2.0",
			"font-size: 38px;" +
			"background-color: #0949f4 ; color: white ; font-weight: bold;padding: 8px 20px; border-radius: 24px;"
		);
    }, [])

    return <div className="w-full h-full bg-gray-200">
        <div className="fixed z-10 w-[1200px] h-[800px] translate-x-[-50%] left-[50%] top-[15%] border rounded-lg shadow-xl overflow-hidden">
            <div className="w-[800px] h-full bg-gray-950"><StarBg /></div>
            <div className=" absolute w-full h-full z-10 flex justify-end top-0">
                <div className="w-[760px] px-[200px] py-[200px] bg-[rgba(255,255,255,1)] relative">
                    <div className="flex gap-4 items-center bg-[#347ef9]">
                        <img src={Logo} className="w-9 h-9" alt="" />
                        <span className="text-[#fff] text-sm">便捷、灵活、可靠的企业级大模型应用开发平台</span>
                    </div>
                    <div className="grid gap-4 mt-6">
                        <div className="grid">
                            <Input
                                id="email"
                                ref={mailRef}
                                placeholder="账号"
                                type="email"
                                autoCapitalize="none"
                                autoComplete="email"
                                autoCorrect="off"
                            />
                        </div>
                        <div className="grid">
                            <Input id="pwd" ref={pwdRef} placeholder="密码" type="password" onKeyDown={e => e.key === 'Enter' && showLogin && handleLogin()} />
                        </div>
                        {
                            !showLogin && <div className="grid">
                                <Input id="pwd" ref={agenPwdRef} placeholder="确认密码" type="password" />
                            </div>
                        }
                        {
                            showLogin ? <>
                                <div className="text-center"><a href="javascript:;" className=" text-blue-500 text-sm underline" onClick={() => setShowLogin(false)}>没有账号，注册</a></div>
                                <Button disabled={isLoading} onClick={handleLogin} >登 录</Button>
                            </> :
                                <>
                                    <div className="text-center"><a href="javascript:;" className=" text-blue-500 text-sm underline" onClick={() => setShowLogin(true)}>已有账号，登录</a></div>
                                    <Button disabled={isLoading} onClick={handleRegister} >注 册</Button>
                                </>
                        }
                    </div>
                    <div className="relative mt-4">
                        <div className="absolute inset-0 flex items-center">
                            <span className="w-full border-t" />
                        </div>
                        <div className="relative flex justify-center text-xs uppercase">
                            <span className="bg-background px-2 text-muted-foreground">其它方式登录</span>
                        </div>
                    </div>
                    <Button variant="outline" type="button" className="mt-4" disabled>Github</Button>
                    {/* link */}
                    <div className=" absolute right-8 bottom-4 flex h-[28px]">
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger className="flex-1 py-1 px-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                    <a href={"https://github.com/dataelement/bisheng"} target="_blank">
                                        <Github className="side-bar-button-size mx-auto" />
                                    </a>
                                </TooltipTrigger>
                                <TooltipContent className="z-10"><p>github</p></TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                        <Separator className="mx-1" orientation="vertical" />
                        <TooltipProvider>
                            <Tooltip>
                                <TooltipTrigger className="flex-1 py-1 px-1 rounded-sm hover:bg-gray-100 dark:hover:bg-gray-600 cursor-pointer">
                                    <a href={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                                        <BookOpen className="side-bar-button-size mx-auto" />
                                    </a>
                                </TooltipTrigger>
                                <TooltipContent className="z-10"><p>文档</p></TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                </div>
            </div>
        </div>
    </div>
};

