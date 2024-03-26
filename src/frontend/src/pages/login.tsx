import { JSEncrypt } from 'jsencrypt';
import { BookOpen, Github } from "lucide-react";
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from 'react-i18next';
import json from "../../package.json";
import { Button } from "../components/bs-ui/button";
import { Input } from "../components/bs-ui/input";
import { Separator } from "../components/ui/separator";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "../components/ui/tooltip";
// import { alertContext } from "../contexts/alertContext";
import { getPublicKeyApi, loginApi, getCaptchaApi, registerApi } from "../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../controllers/request";
import StarBg from "./starBg";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import logoBig from "../assets/login/login-logo-big.png"
import logoSmall from "../assets/login/login-logo-small.png"
import logoLinkRight from "../assets/login/login-link-right.png"
import logoLinkLeft from "../assets/login/login-link-left.png"



export const LoginPage = () => {
    const logoBigUrl = logoBig
    const logoSmallUrl = logoSmall
    const logoLinkRightUrl = logoLinkRight
    const logoLinkLeftUrl = logoLinkLeft




    // const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t, i18n } = useTranslation();
    const { message, toast} = useToast()

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
        if (error.length) return message({
            title: '提示',
            variant: 'warning',
            description: error
        })
        // if (error.length) return setErrorData({
        //     title: `${t('prompt')}:`,
        //     list: error,
        // });

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
        if (!mail) {
            error.push(t('login.pleaseEnterAccount'))
        }
        if (mail.length < 3) {
            error.push(t('login.accountTooShort'))
        }
        if (!/.{8,}/.test(pwd)) {
            error.push(t('login.passwordTooShort'))
        }
        if (!/^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[\W_]).{8,}$/.test(pwd)) {
            error.push(t('login.passwordError'))
        }
        if (pwd !== apwd) {
            error.push(t('login.passwordMismatch'))
        }
        if (captchaData.user_capthca && !captchaRef.current.value) {
            error.push(t('login.pleaseEnterCaptcha'))
        }
        if (error.length){
            return message({
                title: '提示',
                variant: 'warning',
                description: error
            })
        }
        // if (error.length) return setErrorData({
        //     title: `${t('prompt')}:`,
        //     list: error,
        // });

        const encryptPwd = await handleEncrypt(pwd)
        captureAndAlertRequestErrorHoc(registerApi(mail, encryptPwd, captchaData.captcha_key, captchaRef.current?.value).then(res => {
            // setSuccessData({ title: t('login.registrationSuccess') })
            message({
                title: '提示',
                variant: 'success',
                description: [t('login.registrationSuccess')]
            })
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
    return <div className='w-full h-full bg-[#F4F5F8]'>
        <div className='fixed z-10 sm:w-[1280px] w-full sm:h-[720px] h-full translate-x-[-50%] translate-y-[-50%] left-[50%] top-[50%] border rounded-lg shadow-xl overflow-hidden bg-[#fff]'>
        <div className='w-[420px] h-[704px] m-[8px] hidden sm:block'><img src={logoBigUrl} alt="logo_picture" className='w-full h-full'/></div>
        <div className='absolute w-full h-full z-10 flex justify-end top-0'>
            <div className='w-[852px] sm:px-[266px] px-[20px] pyx-[200px] bg-[rgba(255,255,255,1)] dark:bg-gray-950 relative'>
                <div>
                    <img src={logoSmallUrl} alt="small_logo" className='block w-[114px] h-[36px] m-auto mt-[140px]'/>
                    <span className='block w-fit m-auto font-normal text-[14px] text-[rgb(200,200,200)] mt-[24px]'>{t('login.slogen')}</span>
                </div>
                <div className="grid gap-[12px] mt-[68px]">
                        <div className="grid">
                            <Input
                                
                                id="email"
                                className='block h-[48px] bg-[#FCFDFF]'
                                ref={mailRef}
                                placeholder={t('login.account')}
                                type="email"
                                autoCapitalize="none"
                                autoComplete="email"
                                autoCorrect="off"
                            />
                        </div>
                        <div className="grid">
                            <Input 
                            id="pwd" 
                            className='block h-[48px] bg-[#FCFDFF]'
                            ref={pwdRef} 
                            placeholder={t('login.password')} 
                            type="password" 
                            onKeyDown={e => e.key === 'Enter' && showLogin && handleLogin()} />
                        </div>
                        {
                            !showLogin && <div className="grid">
                                <Input id="pwd" 
                                className='block h-[48px] bg-[#FCFDFF]'
                                ref={agenPwdRef} placeholder={t('login.confirmPassword')} type="password" />
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
                                <div className="text-center"><a href="javascript:;" className=" text-blue-500 text-sm hover:underline" onClick={() => setShowLogin(false)}>{t('login.noAccountRegister')}</a></div>
                                <Button 
                                className='h-[48px] mt-[32px]'
                                disabled={isLoading} onClick={handleLogin} >{t('login.loginButton')}</Button>
                            </> :
                                <>
                                    <div className="text-center"><a href="javascript:;" className=" text-blue-500 text-sm hover:underline" onClick={() => setShowLogin(true)}>{t('login.haveAccountLogin')}</a></div>
                                    <Button 
                                    className='h-[48px] mt-[32px]'
                                    disabled={isLoading} onClick={handleRegister} >{t('login.registerButton')}</Button>
                                </>
                        }
                    </div>
                    <div className=" absolute right-[16px] bottom-[16px] flex">
                        <a href={"https://github.com/dataelement/bisheng"} target="_blank">
                            <img className="block h-[40px] w-[40px] gap-1 border p-[10px] rounded-[8px] mx-[8px] hover:bg-[#eeeeee] hover:cursor-pointer" src={logoLinkLeftUrl} alt="github_picture" />
                        </a>
                        <a href={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                            <img className="block h-[40px] w-[40px] gap-1 border p-[10px] rounded-[8px]  hover:bg-[#eeeeee] hover:cursor-pointer" src={logoLinkRightUrl} alt="document_picture" />
                        </a>
                    </div>
            </div>
        </div>
        </div>
        <div className='fixed z-5 whitespace-nowrap translate-x-[-50%] translate-y-[20%] left-[50%] top-[50%]  text-[440px] font-bold text-[#e7e9ee]'>{t('login.bottomText')}</div>
    </div>
};
