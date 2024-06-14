import { useState, useRef, forwardRef, useImperativeHandle } from "react";
import { Button } from "@/components/bs-ui/button";
import { Dialog, DialogClose, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/bs-ui/dialog";
import { Input } from "@/components/bs-ui/input";
import { Pencil2Icon } from "@radix-ui/react-icons";
import { useTranslation } from "react-i18next";
// import { resetUserPasswordApi } from "../controllers/API/user"; // 假设这是重置密码的API函数
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { resetPasswordApi } from "@/controllers/API/user";
import { PWD_RULE, handleEncrypt } from "./utils";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";

interface UserPwdModalProps {
    // onSuccess: () => void;
}

interface UserPwdModalRef {
    open: (userId: string) => void;
}

const UserPwdModal = forwardRef<UserPwdModalRef, UserPwdModalProps>((props, ref) => {
    const { t } = useTranslation();
    const { message } = useToast();

    const [editShow, setEditShow] = useState(false);
    const [error, setError] = useState('');
    const passwordRef = useRef(null)
    const userIdRef = useRef(null);

    useImperativeHandle(ref, () => ({
        open: (userId) => {
            userIdRef.current = userId;
            setEditShow(true);
        }
    }));

    const handleSubmit = async () => {
        // if (!PWD_RULE.test(passwordRef.current.value)) {
        //     return setError(t('login.passwordError'))
        // }

        const cryptPwd = await handleEncrypt(passwordRef.current.value)
        const res = await captureAndAlertRequestErrorHoc(resetPasswordApi(userIdRef.current, cryptPwd));
        if (res) {
            message({
                title: `${t('prompt')}`,
                variant: 'success',
                description: [t('resetPassword.passwordResetSuccess')]
            });
            setEditShow(false);
            // onSuccess();
        }
    };

    return (
        <Dialog open={editShow} onOpenChange={setEditShow}>
            <DialogContent className="sm:max-w-[625px]">
                <DialogHeader>
                    <DialogTitle>{t('resetPassword.resetButton')}</DialogTitle>
                </DialogHeader>
                <div className="flex flex-col gap-8 py-6">
                    <div>
                        <label htmlFor="password" className="bisheng-label">{t('resetPassword.newPassword')}<span className="bisheng-tip">*</span></label>
                        <Input
                            ref={passwordRef}
                            id="password"
                            name="password"
                            type="password"
                            placeholder={t('resetPassword.newPassword')}
                            className="mt-2"
                            onChange={(e) => passwordRef.current.value = e.target.value}
                        />
                        {error && <p className="bisheng-tip mt-1">{error}</p>}
                    </div>
                </div>
                <DialogFooter>
                    <DialogClose>
                        <Button variant="outline" className="px-11" type="button">{t('cancle')}</Button>
                    </DialogClose>
                    <Button type="button" className="px-11" onClick={handleSubmit}>{t('confirmButton')}</Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
});

export default UserPwdModal;
