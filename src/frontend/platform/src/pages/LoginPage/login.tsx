import { BookOpenIcon } from '@/components/bs-icons/bookOpen';
import { GithubIcon } from '@/components/bs-icons/github';
import { useContext, useEffect, useRef, useState } from "react";
import { useTranslation } from 'react-i18next';
import json from "../../../package.json";
import { Button } from "../../components/bs-ui/button";
import { Input } from "../../components/bs-ui/input";
// import { alertContext } from "../contexts/alertContext";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { useLocation, useNavigate } from 'react-router-dom';
import { getCaptchaApi, loginApi, registerApi } from "../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import LoginBridge from './loginBridge';
import { PWD_RULE, handleEncrypt, handleLdapEncrypt } from './utils';
import { locationContext } from '@/contexts/locationContext';
import { ldapLoginApi } from '@/controllers/API/pro';

export const LoginPage = () => {
    // const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t, i18n } = useTranslation();
    const { message, toast } = useToast()
    const navigate = useNavigate()
    const { appConfig } = useContext(locationContext)
    const isLoading = false

    const mailRef = useRef(null)
    const pwdRef = useRef(null)
    const agenPwdRef = useRef(null)

    // login or register
    const [showLogin, setShowLogin] = useState(true)

    useLoginError()

    // captcha
    const captchaRef = useRef(null)
    const [captchaData, setCaptchaData] = useState({ captcha_key: '', user_capthca: false, captcha: '' });

    useEffect(() => {
        fetchCaptchaData();
    }, []);

    const fetchCaptchaData = () => {
        getCaptchaApi().then(setCaptchaData)
    };

    const [isLDAP, setIsLDAP] = useState(false)
    const handleLogin = async () => {
        const error = []
        const [mail, pwd] = [mailRef.current.value, pwdRef.current.value]
        if (!mail) error.push(t('login.pleaseEnterAccount'))
        if (!pwd) error.push(t('login.pleaseEnterPassword'))
        if (captchaData.user_capthca && !captchaRef.current.value) error.push(t('login.pleaseEnterCaptcha'))
        if (error.length) return message({
            title: `${t('prompt')}`,
            variant: 'warning',
            description: error
        })
        // if (error.length) return setErrorData({
        //     title: `${t('prompt')}:`,
        //     list: error,
        // });

        const encryptPwd = isLDAP ? await handleLdapEncrypt(pwd) : await handleEncrypt(pwd)
        captureAndAlertRequestErrorHoc(
            (isLDAP
                ? ldapLoginApi(mail, encryptPwd)
                : loginApi(mail, encryptPwd, captchaData.captcha_key, captchaRef.current?.value)
            ).then((res: any) => {
                window.self === window.top ? localStorage.removeItem('ws_token') : localStorage.setItem('ws_token', res.access_token)
                localStorage.setItem('isLogin', '1')
                // const path = location.href.indexOf('from=workspace') === -1 ? '' : '/workspace'
                const pathname = localStorage.getItem('LOGIN_PATHNAME')
                if (pathname) {
                    // After the login session expires, redirect back to the login page. After successful login, redirect back to the page before login. 
                    localStorage.removeItem('LOGIN_PATHNAME')
                    location.href = pathname
                } else {
                    location.href = location.pathname === '/' ? location.origin + '/workspace/' : location.href
                }
                // location.href = __APP_ENV__.BASE_URL + '/'
            }), (error) => {
                if (error.indexOf('过期') !== -1) { // 有时间改为 code 判断
                    localStorage.setItem('account', mail)
                    navigate('/reset', { state: { noback: true } })
                }
            })

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
        if (!PWD_RULE.test(pwd)) {
            error.push(t('login.passwordError'))
        }
        if (pwd !== apwd) {
            error.push(t('login.passwordMismatch'))
        }
        if (captchaData.user_capthca && !captchaRef.current.value) {
            error.push(t('login.pleaseEnterCaptcha'))
        }
        if (error.length) {
            return message({
                title: `${t('prompt')}`,
                variant: 'warning',
                description: error
            })
        }
        const encryptPwd = await handleEncrypt(pwd)
        captureAndAlertRequestErrorHoc(registerApi(mail, encryptPwd, captchaData.captcha_key, captchaRef.current?.value).then(res => {
            // setSuccessData({ title: t('login.registrationSuccess') })
            message({
                title: `${t('prompt')}`,
                variant: 'success',
                description: [t('login.registrationSuccess')]
            })
            pwdRef.current.value = ''
            setShowLogin(true)
        }))

        fetchCaptchaData()
    }

    return <div className='w-full h-full bg-background-dark'>
        <div className='fixed z-10 sm:w-[1280px] w-full sm:h-[720px] h-full translate-x-[-50%] translate-y-[-50%] left-[50%] top-[50%] border rounded-lg shadow-xl overflow-hidden bg-background-login'>
            <div className='w-[420px] h-[704px] m-[8px] hidden sm:block relative z-20'>
                <img src={__APP_ENV__.BASE_URL + '/assets/bisheng/login-logo-big.png'} alt="logo_picture" className='w-full h-full dark:hidden' />
                <img src={__APP_ENV__.BASE_URL + '/assets/bisheng/login-logo-dark.png'} alt="logo_picture" className='w-full h-full hidden dark:block' />
                {/* <iframe src={__APP_ENV__.BASE_URL + '/face.html'} className='w-full h-full'></iframe> */}
            </div>
            <div className='absolute w-full h-full z-10 flex justify-end top-0'>
                <div className='w-[852px] sm:px-[266px] px-[20px] pyx-[200px] bg-background-login relative'>
                    <div>
                        <img src={__APP_ENV__.BASE_URL + '/assets/bisheng/login-logo-small.png'} className="block w-[114px] h-[36px] m-auto mt-[140px] dark:w-[124px] dark:pr-[10px] dark:hidden" alt="" />
                        <img src={__APP_ENV__.BASE_URL + '/assets/bisheng/logo-small-dark.png'} className="w-[114px] h-[36px] m-auto mt-[140px] dark:w-[124px] dark:pr-[10px] dark:block hidden" alt="" />
                        <span className='block w-fit m-auto font-normal text-[14px] text-tx-color mt-[24px]'>{t('login.slogen')}</span>
                    </div>
                    <div className="grid gap-[12px] mt-[68px]">
                        <div className="grid">
                            <Input
                                id="email"
                                className='h-[48px] dark:bg-login-input'
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
                                className='h-[48px] dark:bg-login-input'
                                ref={pwdRef}
                                placeholder={t('login.password')}
                                type="password"
                                onKeyDown={e => e.key === 'Enter' && showLogin && handleLogin()} />
                        </div>
                        {
                            !showLogin && <div className="grid">
                                <Input id="pwd"
                                    className='h-[48px] dark:bg-login-input'
                                    ref={agenPwdRef}
                                    placeholder={t('login.confirmPassword')}
                                    type="password" />
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
                                <div className="text-center">
                                    {!isLDAP && appConfig.register && <a href="javascript:;" className=" text-blue-500 text-sm hover:underline" onClick={() => setShowLogin(false)}>{t('login.noAccountRegister')}</a>}
                                </div>
                                <Button
                                    className='h-[48px] mt-[32px] dark:bg-button'
                                    disabled={isLoading} onClick={handleLogin} >{t('login.loginButton')}</Button>
                            </> :
                                <>
                                    <div className="text-center">
                                        <a href="javascript:;" className=" text-blue-500 text-sm hover:underline" onClick={() => setShowLogin(true)}>{t('login.haveAccountLogin')}</a>
                                    </div>
                                    <Button
                                        className='h-[48px] mt-[32px] dark:bg-button'
                                        disabled={isLoading} onClick={handleRegister} >{t('login.registerButton')}</Button>
                                </>
                        }
                        {appConfig.isPro && <LoginBridge onHasLdap={setIsLDAP} />}
                    </div>
                    <div className=" absolute right-[16px] bottom-[16px] flex">
                        <span className="mr-4 text-sm text-gray-400 relative top-2">v{json.version}</span>
                        {!appConfig.noFace && <div className='help flex'>
                            <a href={"https://github.com/dataelement/bisheng"} target="_blank">
                                <GithubIcon className="block h-[40px] w-[40px] gap-1 border p-[10px] rounded-[8px] mx-[8px] hover:bg-[#1b1f23] hover:text-[white] hover:cursor-pointer" />
                            </a>
                            <a href={"https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"} target="_blank">
                                <BookOpenIcon className="block h-[40px] w-[40px] gap-1 border p-[10px] rounded-[8px]  hover:bg-[#0055e3] hover:text-[white] hover:cursor-pointer" />
                            </a>
                        </div>}
                    </div>
                </div>
            </div>
        </div>
    </div>
};




export const useLoginError = () => {
    const location = useLocation();
    const { toast } = useToast();
    const { t } = useTranslation();

    useEffect(() => {
        const queryParams = new URLSearchParams(location.search);
        const code = queryParams.get('status_code')
        if (code) {
            toast({
                variant: 'error',
                description: t('errors.' + code)
            })
        }
    }, [location])
}