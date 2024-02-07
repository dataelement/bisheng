import { JSEncrypt } from 'jsencrypt';
import { BookOpen, Github } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from 'react-i18next';
import json from "../../package.json";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Separator } from "../components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
import { alertContext } from "../contexts/alertContext";
import { getPublicKeyApi, loginApi, getCaptchaApi, registerApi } from "../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../controllers/request";
import StarBg from "./starBg";

export const LoginPage = () => {
    const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t, i18n } = useTranslation();

    const isLoading = false

    const mailRef = useRef(null)
    const pwdRef = useRef(null)
    const agenPwdRef = useRef(null)

    // login or register
    const [showLogin, setShowLogin] = useState(true)

    // captcha
    const captchaRef = useRef(null)
    const [captchaData, setCaptchaData] = useState({ captcha_key: '', user_capthca: false, captcha: '' });

    useEffect(() => {
        fetchCaptchaData();
    }, []);

    const fetchCaptchaData = () => {
        getCaptchaApi().then(setCaptchaData)
    };

    const handleLogin = async () => {
        const error = []
        const [mail, pwd] = [mailRef.current.value, pwdRef.current.value]
        if (!mail) error.push(t('login.pleaseEnterAccount'))
        if (!pwd) error.push(t('login.pleaseEnterPassword'))
        if (captchaData.user_capthca && !captchaRef.current.value) error.push(t('login.pleaseEnterCaptcha'))
        if (error.length) return setErrorData({
            title: `${t('prompt')}:`,
            list: error,
        });

        const encryptPwd = await handleEncrypt(pwd)
        captureAndAlertRequestErrorHoc(loginApi(mail, encryptPwd, captchaData.captcha_key, captchaRef.current?.value).then((res: any) => {
            // setUser(res.data)
            localStorage.setItem('ws_token', res.access_token)
            localStorage.setItem('isLogin', '1')
            location.href = '/'
        }))

        fetchCaptchaData()
    }

    const handleRegister = async () => {
        const error = []
        const [mail, pwd, apwd] = [mailRef.current.value, pwdRef.current.value, agenPwdRef.current.value]
        if (!mail) error.push(t('login.pleaseEnterAccount'))
        if (mail.length < 3) error.push(t('login.accountTooShort'))
        if (!/.{8,}/.test(pwd)) error.push(t('login.passwordTooShort'))
        if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$/.test(pwd)) error.push(t('login.passwordError'))
        if (pwd !== apwd) error.push(t('login.passwordMismatch'))
        if (captchaData.user_capthca && !captchaRef.current.value) error.push(t('login.pleaseEnterCaptcha'))
        if (error.length) return setErrorData({
            title: `${t('prompt')}:`,
            list: error,
        });

        const encryptPwd = await handleEncrypt(pwd)
        captureAndAlertRequestErrorHoc(registerApi(mail, encryptPwd, captchaData.captcha_key, captchaRef.current?.value).then(res => {
            setSuccessData({ title: t('login.registrationSuccess') })
            pwdRef.current.value = ''
            setShowLogin(true)
        }))

        fetchCaptchaData()
    }

    const handleEncrypt = async (pwd) => {
        const { public_key } = await getPublicKeyApi()
        const encrypt = new JSEncrypt()
        encrypt.setPublicKey(public_key)
        return encrypt.encrypt(pwd) as string
    }

    return <div className="w-full h-full bg-gray-200 dark:bg-gray-700">
        <div className="fixed z-10 sm:w-[1200px] w-full sm:h-[750px] h-full translate-x-[-50%] translate-y-[-50%] left-[50%] top-[50%] border rounded-lg shadow-xl overflow-hidden">
            <div className="w-[800px] h-full bg-gray-950 hidden sm:block"><StarBg /></div>
            <div className=" absolute w-full h-full z-10 flex justify-end top-0">
                <div className="w-[760px] sm:px-[200px] px-[20px] py-[200px] bg-[rgba(255,255,255,1)] dark:bg-gray-950 relative">
                    <div className="flex gap-4 items-center bg-[#347ef9]">
                        <img src='/logo.jpeg' className="w-9 h-9" alt="" />
                        <span className="text-[#fff] text-sm">{t('login.slogen')}</span>
                    </div>
                    <div className="grid gap-4 mt-6">
                        <div className="grid">
                            <Input
                                id="email"
                                ref={mailRef}
                                placeholder={t('login.account')}
                                type="email"
                                autoCapitalize="none"
                                autoComplete="email"
                                autoCorrect="off"
                            />
                        </div>
                        <div className="grid">
                            <Input id="pwd" ref={pwdRef} placeholder={t('login.password')} type="password" onKeyDown={e => e.key === 'Enter' && showLogin && handleLogin()} />
                        </div>
                        {
                            !showLogin && <div className="grid">
                                <Input id="pwd" ref={agenPwdRef} placeholder={t('login.confirmPassword')} type="password" />
                            </div>
                        }
                        {
                            captchaData.user_capthca && (<div className="flex items-center gap-4">
                                <Input
                                    type="text"
                                    ref={captchaRef}
                                    placeholder={t('login.pleaseEnterCaptcha')}
                                    className="form-input px-4 py-2 border border-gray-300 focus:outline-none"
                                />
                                <img
                                    src={'data:image/jpg;base64,' + captchaData.captcha} // 这里应该是你的验证码图片的URL
                                    alt="captcha"
                                    onClick={fetchCaptchaData} // 这里应该是你的刷新验证码函数
                                    className="cursor-pointer h-10 bg-gray-100 border border-gray-300"
                                    style={{ width: '120px' }} // 根据需要调整宽度
                                />
                            </div>
                            )
                        }
                        {
                            showLogin ? <>
                                <div className="text-center"><a href="javascript:;" className=" text-blue-500 text-sm underline" onClick={() => setShowLogin(false)}>{t('login.noAccountRegister')}</a></div>
                                <Button disabled={isLoading} onClick={handleLogin} >{t('login.loginButton')}</Button>
                            </> :
                                <>
                                    <div className="text-center"><a href="javascript:;" className=" text-blue-500 text-sm underline" onClick={() => setShowLogin(true)}>{t('login.haveAccountLogin')}</a></div>
                                    <Button disabled={isLoading} onClick={handleRegister} >{t('login.registerButton')}</Button>
                                </>
                        }
                    </div>
                    <div className="relative mt-4">
                        <div className="absolute inset-0 flex items-center">
                            <span className="w-full border-t" />
                        </div>
                        {/* <div className="relative flex justify-center text-xs uppercase">
                            <span className="bg-background px-2 text-muted-foreground">其它方式登录</span>
                        </div> */}
                    </div>
                    {/* <Button variant="outline" type="button" className="mt-4" disabled>Github</Button> */}
                    {/* link */}
                    <div className=" absolute right-8 bottom-4 flex h-[28px]">
                        <span className="mr-4 text-sm text-gray-400 relative top-2">v{json.version}</span>
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
                                <TooltipContent className="z-10"><p>{t('login.document')}</p></TooltipContent>
                            </Tooltip>
                        </TooltipProvider>
                    </div>
                </div>
            </div>
        </div>
    </div>
};
