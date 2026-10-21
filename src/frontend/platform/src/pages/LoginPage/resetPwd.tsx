// @ts-strict-ignore
import { Button, PasswordInput, toast } from '@bisheng/ui';

import { Outlined } from "bisheng-icons";

import { getBrandAssetUrl } from "@/utils/brand";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";


import { changePasswordApi, loggedChangePasswordApi } from "../../controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "../../controllers/request";
import { PWD_RULE, handleEncrypt } from "./utils";

export const ResetPwdPage = () => {
    const { t } = useTranslation();

    const { state } = useLocation();
    const navigate = useNavigate();

    useEffect(() => {
        state?.noback &&
            toast.show({ type: "warning", message: [String(`${t("prompt")}`), String(t("publicPages.passwordExpired") ?? '')].filter(Boolean).join('\n') });
    }, []);

    const currentPwdRef = useRef<HTMLInputElement>(null);
    const newPwdRef = useRef<HTMLInputElement>(null);
    const confirmPwdRef = useRef<HTMLInputElement>(null);

    const handleResetPassword = async () => {
        const errors: string[] = [];
        const [currentPwd, newPwd, confirmPwd] = [
            currentPwdRef.current?.value,
            newPwdRef.current?.value,
            confirmPwdRef.current?.value,
        ];

        if (!currentPwd) errors.push(t("resetPassword.pleaseEnterCurrentPassword"));
        if (!newPwd) errors.push(t("resetPassword.pleaseEnterNewPassword"));
        if (!confirmPwd) errors.push(t("resetPassword.pleaseEnterConfirmPassword"));
        if (!/.{8,}/.test(newPwd)) errors.push(t("resetPassword.newPasswordTooShort"));
        if (!PWD_RULE.test(newPwd)) errors.push(t("login.passwordError"));
        if (newPwd !== confirmPwd) errors.push(t("resetPassword.passwordMismatch"));

        if (errors.length) {
            return toast.show({ type: "warning", message: [String(`${t("prompt")}`), errors.filter(Boolean).join('\n')].filter(Boolean).join('\n') });
        }

        const account = localStorage.getItem("account");
        const encryptCurrentPwd = await handleEncrypt(currentPwd);
        const encryptNewPwd = await handleEncrypt(newPwd);

        console.log(state);
        const res = await captureAndAlertRequestErrorHoc(
            state
                ? changePasswordApi(account, encryptCurrentPwd, encryptNewPwd)
                : loggedChangePasswordApi(encryptCurrentPwd, encryptNewPwd),
        );
        if (res === null) {
            toast.show({ type: "success", message: [String(`${t("prompt")}`), ([t("resetPassword.passwordResetSuccess")]).filter(Boolean).join('\n')].filter(Boolean).join('\n') });
            // Clear input fields
            if (currentPwdRef.current) currentPwdRef.current.value = "";
            if (newPwdRef.current) newPwdRef.current.value = "";
            if (confirmPwdRef.current) confirmPwdRef.current.value = "";
            // if (!state?.noback) {
            navigate(-1);
            // }
        }
        // }));
    };

    return (
        <div className="w-full h-full bg-background-dark">
            <div className="fixed z-10 sm:w-[600px] px-[120px] w-full sm:h-[720px] h-full translate-x-[-50%] translate-y-[-50%] left-[50%] top-[50%] border rounded-lg shadow-xl overflow-hidden bg-background-login">
                {!state?.noback && (
                    <Button variant="outlined" size="small" iconOnly className="absolute left-4 top-4" aria-label={t("back")} onClick={() => navigate(-1)} color="default">
                        <Outlined.ArrowLeft />
                    </Button>
                )}
                <div className="bg-background-login relative">
                    <div>
                        <img
                            src={getBrandAssetUrl("headerLogoLight", "/assets/bisheng/login-logo-small.png")}
                            alt="small_logo"
                            className="block w-[114px] h-[36px] m-auto mt-[140px]"
                        />
                        <span className="block w-fit m-auto font-normal text-[14px] text-tx-color mt-[24px]">
                            {t("resetPassword.slogen")}
                        </span>
                    </div>
                    <div className="grid gap-[12px] mt-[68px]">
                        <div className="grid">
                            <PasswordInput size="large" id="currentPassword" ref={currentPwdRef} placeholder={t("resetPassword.currentPassword")} className={"dark:bg-login-input"} revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
                        </div>
                        <div className="grid">
                            <PasswordInput size="large" id="newPassword" ref={newPwdRef} placeholder={t("resetPassword.newPassword")} className={"dark:bg-login-input"} revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
                        </div>
                        <div className="grid">
                            <PasswordInput size="large" id="confirmNewPassword" ref={confirmPwdRef} placeholder={t("resetPassword.confirmNewPassword")} className={"dark:bg-login-input"} revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
                        </div>
                        <Button size="large" className="mt-[32px]" onClick={handleResetPassword}>
                            {t("resetPassword.resetButton")}
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ResetPwdPage;
