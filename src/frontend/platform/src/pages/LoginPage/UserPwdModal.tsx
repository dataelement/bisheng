// @ts-strict-ignore
import { Button, PasswordInput, toast } from '@bisheng/ui';

import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/bs-ui/dialog";

import { forwardRef, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";


import { resetPasswordApi } from "@/controllers/API/user";
import { handleUiRequest } from "@/controllers/request";
import { handleEncrypt, PWD_RULE } from "./utils";

interface UserPwdModalProps {
    // onSuccess: () => void;
}

interface UserPwdModalRef {
    open: (userId: string) => void;
}

const UserPwdModal = forwardRef<UserPwdModalRef, UserPwdModalProps>((props, ref) => {
    const { t } = useTranslation();


    const [editShow, setEditShow] = useState(false);
    const [error, setError] = useState("");
    const passwordRef = useRef(null);
    const userIdRef = useRef(null);

    useImperativeHandle(ref, () => ({
        open: (userId) => {
            userIdRef.current = userId;
            setEditShow(true);
        },
    }));

    const handleSubmit = async () => {
        // if (!PWD_RULE.test(passwordRef.current.value)) {
        //     return setError(t('login.passwordError'))
        // }
        const errors: string[] = [];
        if (!passwordRef.current.value) errors.push(t("resetPassword.notEmpty"));
        if (!/.{8,}/.test(passwordRef.current.value)) errors.push(t("resetPassword.newPasswordTooShort"));
        if (!PWD_RULE.test(passwordRef.current.value)) errors.push(t("login.passwordError"));

        if (errors.length) return toast.show({ type: "error", message: [String(t("prompt") ?? ''), errors.filter(Boolean).join('\n')].filter(Boolean).join('\n') });

        const cryptPwd = await handleEncrypt(passwordRef.current.value);
        const res = await resetPasswordApi(userIdRef.current, cryptPwd);
        if (res === null) {
            toast.show({ type: "success", message: [String(`${t("prompt")}`), ([t("resetPassword.adminResetSuccess")]).filter(Boolean).join('\n')].filter(Boolean).join('\n') });
            setEditShow(false);
            // onSuccess();
        }
    };

    return (
        <Dialog open={editShow} onOpenChange={setEditShow}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{t("resetPassword.resetButton")}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-8 py-6">
                    <div>
                        <label htmlFor="password" className="bisheng-label">
                            {t("resetPassword.newPassword")}
                            <span className="bisheng-tip">*</span>
                        </label>
                        <PasswordInput ref={passwordRef} id="password" name="password" placeholder={t("resetPassword.newPassword")} onChange={(e) => (passwordRef.current.value = e.target.value)} className={"mt-2"} revealLabel={t('sharedUi.showPassword')} hideLabel={t('sharedUi.hidePassword')} />
                        {error && <p className="bisheng-tip mt-1">{error}</p>}
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outlined" type="button" color="default">
                            {t("cancle")}
                        </Button>
                    </DialogClose>
                    <Button type="button" onClick={handleUiRequest(handleSubmit)}>
                        {t("confirmButton")}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

export default UserPwdModal;
