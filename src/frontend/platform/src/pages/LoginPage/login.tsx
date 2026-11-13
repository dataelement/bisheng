// @ts-strict-ignore
import { Button, Input, Tooltip, toast, notification } from '@bisheng/ui';
import { LoadingIcon } from "@/components/bs-icons/loading";
import { Checkbox } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { GithubIcon } from "@/components/bs-icons/github";

import { useContext, useEffect, useLayoutEffect, useRef, useState, type MouseEvent } from "react";
import { useTranslation } from "react-i18next";
import json from "../../../package.json";


// import { alertContext } from "../contexts/alertContext";

import { locationContext } from "@/contexts/locationContext";
import { getSSOurlApi, ldapLoginApi } from "@/controllers/API/pro";
import { getBrandAssetUrl } from "@/utils/brand";
import { consumeLoginReturnTo } from "@/utils/loginReturnTo";
import { getWorkspaceClientUrl } from "@/utils/workspaceUrl";
import { useLocation, useNavigate } from "react-router-dom";
import { getCaptchaApi, loginApi } from "../../controllers/API/user";
import { showApiError } from "../../controllers/request";
import LoginBridge from "./loginBridge";
import { handleEncrypt, handleLdapEncrypt } from "./utils";
import { RegistrationForm } from './RegistrationForm';

interface LoginPageProps {
    // Backdoor entry: skip SSO auto-redirect and clear any stored third-party
    // redirect URLs so 401/logout flows do not bounce admins back to the IdP.
    forceLocal?: boolean;
}

type RegistrationLayout = {
    panelTop: number;
    formTop: number;
    loginHeight: number;
    accountHeight: number;
};

const formTransition = { duration: 240, easing: "cubic-bezier(0.2, 0, 0, 1)" };

function formClip(height: number, visibleHeight = height) {
    return `inset(-4px -4px ${height - visibleHeight}px)`;
}

function animateFormHeight(fields: HTMLElement, from: number, to: number, fill?: FillMode) {
    return fields.animate([{ height: `${from}px` }, { height: `${to}px` }], { ...formTransition, fill });
}

function canAnimateForm(fields: HTMLElement) {
    return typeof fields.animate === "function" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export const LoginPage = ({ forceLocal = false }: LoginPageProps) => {
    // const { setErrorData, setSuccessData } = useContext(alertContext);
    const { t, i18n } = useTranslation();

    const navigate = useNavigate();
    const { appConfig } = useContext(locationContext);
    const isLoading = false;

    const personIdRef = useRef(null);
    const pwdRef = useRef(null);

    const layoutRef = useRef<HTMLDivElement>(null);
    const formRef = useRef<HTMLDivElement>(null);
    const fieldsRef = useRef<HTMLDivElement>(null);
    const loginFieldsRef = useRef<HTMLDivElement>(null);
    const registrationFieldsRef = useRef<HTMLDivElement>(null);
    const [registrationLayout, setRegistrationLayout] = useState<RegistrationLayout | null>(null);
    const [returningToLogin, setReturningToLogin] = useState(false);
    const showLogin = registrationLayout === null;

    const handleShowRegistration = (event: MouseEvent<HTMLAnchorElement>) => {
        event.preventDefault();
        const layout = layoutRef.current;
        const form = formRef.current;
        const fields = fieldsRef.current;
        const account = loginFieldsRef.current?.firstElementChild;
        const page = layout?.parentElement;
        if (!layout || !form || !fields || !account || !page) return;

        // Preserve the centered login title's position while registration grows below it.
        const panelTop = layout.getBoundingClientRect().top;
        setRegistrationLayout({
            panelTop: panelTop - page.getBoundingClientRect().top,
            formTop: form.getBoundingClientRect().top - panelTop,
            loginHeight: fields.getBoundingClientRect().height,
            accountHeight: account.getBoundingClientRect().height,
        });
    };

    useLayoutEffect(() => {
        const fields = fieldsRef.current;
        const registration = registrationFieldsRef.current;
        if (!registrationLayout || !fields || !registration || !canAnimateForm(fields)) return;

        const height = registration.getBoundingClientRect().height;
        const resize = animateFormHeight(fields, registrationLayout.loginHeight, height);
        const reveal = registration.animate([
            { clipPath: formClip(height, registrationLayout.accountHeight) },
            { clipPath: formClip(height) },
        ], formTransition);
        return () => {
            resize.cancel();
            reveal.cancel();
        };
    }, [registrationLayout]);

    useLayoutEffect(() => {
        const fields = fieldsRef.current;
        const login = loginFieldsRef.current;
        const registration = registrationFieldsRef.current;
        if (!returningToLogin || !registrationLayout || !fields || !login || !registration) return;

        // Fade the login layer over the folding form so the account row never goes blank.
        const resize = animateFormHeight(fields, fields.getBoundingClientRect().height, login.getBoundingClientRect().height, "forwards");
        const height = registration.getBoundingClientRect().height;
        const currentClip = window.getComputedStyle(registration).clipPath;
        const fold = registration.animate([
            { clipPath: currentClip === "none" ? formClip(height) : currentClip },
            { clipPath: formClip(height, registrationLayout.accountHeight) },
        ], { ...formTransition, fill: "forwards" });
        const reveal = login.animate([{ opacity: 0 }, { opacity: 1 }], { ...formTransition, fill: "forwards" });
        registration.inert = true;
        login.inert = true;
        resize.onfinish = () => {
            setRegistrationLayout(null);
            setReturningToLogin(false);
        };

        return () => {
            resize.cancel();
            fold.cancel();
            reveal.cancel();
            login.inert = false;
        };
    }, [registrationLayout, returningToLogin]);

    const handleShowLogin = () => {
        if (!registrationLayout || returningToLogin) return;
        const fields = fieldsRef.current;
        if (fields && canAnimateForm(fields)) {
            setReturningToLogin(true);
        } else {
            setRegistrationLayout(null);
        }
    };

    // Check third-party redirect login before rendering the login form
    const [oauthLoading, setOauthLoading] = useState(true);
    const [oauthData, setOauthData] = useState<any>(null);

    useEffect(() => {
        if (forceLocal) {
            // Strip any stale third-party URLs left by a previous visit to `/`,
            // otherwise the 401 interceptor and logout handlers would still
            // redirect this session to the IdP.
            localStorage.removeItem("THIRD_PARTY_LOGIN_URL");
            localStorage.removeItem("THIRD_PARTY_LOGOUT_URL");
        }
        getSSOurlApi()
            .then((urls: any) => {
                setOauthData(urls);
                if (urls?.ldap) {
                    setHasLdap(true);
                }
                if (urls?.ldapCheckboxLabel) {
                    setLdapCheckboxLabel(urls.ldapCheckboxLabel);
                    setIsLdapLogin(true);
                }
                if (forceLocal) {
                    // Backdoor route: never persist redirect URLs and never auto-jump.
                    setOauthLoading(false);
                    return;
                }
                // Persist redirect URLs for interceptor access (401 / logout)
                if (urls?.redirect_login_url) {
                    localStorage.setItem("THIRD_PARTY_LOGIN_URL", urls.redirect_login_url);
                } else {
                    localStorage.removeItem("THIRD_PARTY_LOGIN_URL");
                }
                if (urls?.redirect_logout_url) {
                    localStorage.setItem("THIRD_PARTY_LOGOUT_URL", urls.redirect_logout_url);
                } else {
                    localStorage.removeItem("THIRD_PARTY_LOGOUT_URL");
                }
                // Redirect immediately if third-party login URL is configured
                if (urls?.redirect_login_url) {
                    window.location.href = urls.redirect_login_url;
                    return;
                }
                setOauthLoading(false);
            })
            .catch(() => {
                // Third-party service unavailable — fall through to normal login
                setOauthLoading(false);
            });
    }, [forceLocal]);

    useLoginError();

    // captcha
    const captchaRef = useRef(null);
    const [captchaData, setCaptchaData] = useState({ captcha_key: "", user_capthca: false, captcha: "" });

    useEffect(() => {
        fetchCaptchaData();
    }, []);

    const fetchCaptchaData = () => {
        getCaptchaApi()
            .then((raw: any) => {
                const rawFlag = raw?.user_capthca ?? raw?.user_captcha;
                const enabled =
                    rawFlag === true ||
                    rawFlag === 1 ||
                    (typeof rawFlag === "string" &&
                        ["true", "1", "yes", "on"].includes(String(rawFlag).trim().toLowerCase()));
                setCaptchaData({
                    captcha_key: raw?.captcha_key ?? "",
                    captcha: raw?.captcha ?? "",
                    user_capthca: enabled,
                });
            })
            .catch(() => {
                setCaptchaData({ captcha_key: "", captcha: "", user_capthca: false });
            });
    };

    const [hasLdap, setHasLdap] = useState(false);
    const [ldapCheckboxLabel, setLdapCheckboxLabel] = useState("");
    const [isLdapLogin, setIsLdapLogin] = useState(true);
    const enableDualLogin = hasLdap && !!ldapCheckboxLabel;

    const shouldUseLdap = hasLdap && !!ldapCheckboxLabel && isLdapLogin;
    const showCaptcha = captchaData.user_capthca && !shouldUseLdap;

    const handleLogin = async () => {
        const error = [];
        const [personId, pwd] = [personIdRef.current.value, pwdRef.current.value];
        if (!personId) error.push(t("login.pleaseEnterPersonId"));
        if (!pwd) error.push(t("login.pleaseEnterPassword"));
        if (!shouldUseLdap && captchaData.user_capthca && !captchaRef.current.value)
            error.push(t("login.pleaseEnterCaptcha"));
        if (error.length)
            return toast.show({ type: "warning", message: [String(`${t("prompt")}`), error.filter(Boolean).join('\n')].filter(Boolean).join('\n') });
        // if (error.length) return setErrorData({
        //     title: `${t('prompt')}:`,
        //     list: error,
        // });

        const encryptPwd = shouldUseLdap ? await handleLdapEncrypt(pwd) : await handleEncrypt(pwd);
        (shouldUseLdap
                ? ldapLoginApi(personId, encryptPwd)
                : loginApi(personId, encryptPwd, captchaData.captcha_key, captchaRef.current?.value)
            ).then((res: any) => {
                // v2.5.1: leaf tenant is derived from the user's primary department.
                // Ignore any stale "requires_tenant_selection" response fields.
                if (res.requires_tenant_selection) {
                    sessionStorage.removeItem("pending_tenants");
                }

                window.self === window.top
                    ? localStorage.removeItem("ws_token")
                    : localStorage.setItem("ws_token", res.access_token);
                localStorage.setItem("isLogin", "1");
                // A 401 anywhere in the two SPAs stores where the user was; come
                // back to it. Validated + consumed in one place so this path and
                // the SSO landing in App.tsx cannot drift apart.
                const returnTo = consumeLoginReturnTo();
                if (returnTo) {
                    location.href = returnTo;
                } else {
                    const entry = (res as { default_entry?: string }).default_entry;
                    if (entry === "workspace") {
                        location.href = getWorkspaceClientUrl("/");
                    } else {
                        // Both areas or admin-only: default to admin shell first.
                        location.href = `${__APP_ENV__.BASE_URL}/admin`;
                    }
                }
            }).catch((error) => {
                if ((error?.status_code ?? error?.code) === 10601) {
                    // Password expired.
                    localStorage.setItem("account", personId);
                    navigate("/reset", { state: { noback: true } });
                    return;
                }
                showApiError(error);
            });

        fetchCaptchaData();
    };

    // Show loading spinner while checking for third-party redirect
    if (oauthLoading) {
        return (
            <div className="w-full h-full bg-background-dark flex justify-center items-center">
                <LoadingIcon className="w-48 text-primary" />
            </div>
        );
    }

    return (
        <div className="flex min-h-dvh w-full flex-col items-center bg-background-dark md:px-4">
            <div
                ref={layoutRef}
                className="my-auto grid min-h-dvh w-full max-w-[1280px] shrink-0 grid-cols-1 bg-background-login md:min-h-[min(720px,100dvh)] md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] md:rounded-lg"
                style={registrationLayout ? { marginBlockStart: registrationLayout.panelTop, marginBlockEnd: 0 } : undefined}
            >
                <div className="relative my-2 ml-2 hidden overflow-hidden rounded-lg md:block">
                    <img
                        src={getBrandAssetUrl("loginHeroLight", "/assets/bisheng/login-logo-big.png")}
                        alt=""
                        className="absolute inset-0 h-full w-full object-cover dark:hidden"
                    />
                    <img
                        src={getBrandAssetUrl("loginHeroDark", "/assets/bisheng/login-logo-dark.png")}
                        alt=""
                        className="absolute inset-0 hidden h-full w-full object-cover dark:block"
                    />
                </div>
                <div
                    className="grid min-w-0 grid-rows-[minmax(1rem,1fr)_auto_minmax(min-content,1fr)]"
                    style={registrationLayout ? { gridTemplateRows: `${registrationLayout.formTop}px auto minmax(min-content, 1fr)` } : undefined}
                >
                    <div ref={formRef} className="row-start-2 mx-auto w-full max-w-[360px] px-5">
                        <div>
                            <img
                                src={getBrandAssetUrl("headerLogoLight", "/assets/bisheng/login-logo-small.png")}
                                className="m-auto block h-[36px] w-[114px] dark:hidden"
                                alt=""
                            />
                            <img
                                src={getBrandAssetUrl("headerLogoDark", "/assets/bisheng/logo-small-dark.png")}
                                className="m-auto hidden h-[36px] w-[124px] pr-[10px] dark:block"
                                alt=""
                            />
                            <span className="mt-6 block break-words text-center text-body text-tx-color">
                                {t("login.slogen")}
                            </span>
                        </div>
                        <div ref={fieldsRef} className="relative mt-8 grid grid-cols-1 content-start md:[@media(min-height:752px)]:mt-[68px]">
                            {(showLogin || returningToLogin) && (
                                <div ref={loginFieldsRef} className={`grid content-start gap-3 ${returningToLogin ? "absolute inset-x-0 top-0 z-10 bg-background-login" : ""}`}>
                                    <div className="grid">
                                        <Input size="large" id="email" ref={personIdRef} placeholder={t("login.account")} type="text" autoCapitalize="none" autoComplete="username" autoCorrect="off" />
                                    </div>
                                    <div className="grid">
                                        <Input size="large" id="pwd" ref={pwdRef} placeholder={t("login.password")} type="password" onKeyDown={(e) => e.key === "Enter" && showLogin && handleLogin()} />
                                    </div>
                                    {showCaptcha && (
                                        <div className="flex items-center gap-4">
                                            <Input size="large" type="text" ref={captchaRef} className="min-w-0 flex-1" placeholder={t("login.pleaseEnterCaptcha")} />
                                            <img
                                                src={"data:image/jpg;base64," + captchaData.captcha}
                                                alt="captcha"
                                                onClick={fetchCaptchaData}
                                                className="h-10 w-[120px] shrink-0 cursor-pointer border border-gray-300 bg-gray-100"
                                            />
                                        </div>
                                    )}
                                    {enableDualLogin && (
                                        <label className="flex items-center gap-2 text-sm text-tx-color">
                                            <Checkbox
                                                checked={isLdapLogin}
                                                onCheckedChange={(checked) => setIsLdapLogin(checked === true)}
                                            />
                                            <span className="min-w-0 break-words">{ldapCheckboxLabel}</span>
                                        </label>
                                    )}
                                    <div className="text-center">
                                        {!shouldUseLdap && appConfig.register && (
                                            <a
                                                href="/login"
                                                className=" text-blue-500 text-sm hover:underline"
                                                onClick={handleShowRegistration}
                                            >
                                                {t("login.noAccountRegister")}
                                            </a>
                                        )}
                                    </div>
                                    <Button size="large" className="mt-4 md:[@media(min-height:752px)]:mt-8" disabled={isLoading} onClick={handleLogin}>
                                        {t("login.loginButton")}
                                    </Button>
                                    {appConfig.isPro && <LoginBridge oauthData={oauthData} onHasLdap={setHasLdap} />}
                                </div>
                            )}
                            {!showLogin && (
                                <div ref={registrationFieldsRef}>
                                    <RegistrationForm captcha={captchaData} onRefreshCaptcha={fetchCaptchaData}
                                        onLogin={handleShowLogin} onSuccess={handleShowLogin} />
                                </div>
                            )}
                        </div>
                    </div>
                    <div className="row-start-3 flex flex-wrap items-center justify-end gap-x-6 gap-y-2 self-end px-4 pb-4 pt-2 md:pt-4">
                            <span className="text-sm text-gray-400">v{json.version}</span>
                            {!appConfig.noFace && (
                                <div className="flex gap-2">
                                    <Tooltip content={t("menu.github")}>
                                        <Button asChild size="medium" color="default" variant="outlined" iconOnly>
                                            <a href="https://github.com/dataelement/bisheng" target="_blank" rel="noopener noreferrer" aria-label={t("menu.github")}>
                                                <GithubIcon aria-hidden="true" />
                                            </a>
                                        </Button>
                                    </Tooltip>
                                    <Tooltip content={t("menu.bookopen")}>
                                        <Button asChild size="medium" color="default" variant="outlined" iconOnly>
                                            <a
                                                href="https://m7a7tqsztt.feishu.cn/wiki/ZxW6wZyAJicX4WkG0NqcWsbynde"
                                                target="_blank"
                                                rel="noopener noreferrer"
                                                aria-label={t("menu.bookopen")}
                                            >
                                                <Outlined.BookOpenText aria-hidden="true" />
                                            </a>
                                        </Button>
                                    </Tooltip>
                                </div>
                            )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export const useLoginError = () => {
    const location = useLocation();

    const { t } = useTranslation();

    useEffect(() => {
        const queryParams = new URLSearchParams(location.search);
        const code = queryParams.get("status_code");
        if (code) {
            notification.open({ type: "error", description: String(t("errors." + code) ?? '') });
        }
    }, [location]);
};
