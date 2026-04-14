import { useEffect, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSetRecoilState } from "recoil";
import { X, Eye, EyeOff, Camera } from "lucide-react";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Dialog, DialogContent } from "~/components/ui/Dialog";
import { cn } from "~/utils";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { updatePasswordApi, uploadUserAvatarFileApi, getPublicKeyApi } from "~/api/user";
import { JSEncrypt } from 'jsencrypt';
import store from "~/store";
import { QueryKeys } from "~/types/chat";
import { useLocalize } from "~/hooks";


interface PasswordStrength {
    minLength: boolean;
    hasAllRequired: boolean;
}

function PasswordStrengthRow({ met, children }: { met: boolean; children: ReactNode }) {
    return (
        <div className="flex items-start gap-2 text-[12px] leading-5">
            <span
                className={cn("mt-[5px] size-1.5 shrink-0 rounded-full", met ? "bg-[#25C298]" : "bg-[#c9cdd4]")}
                aria-hidden
            />
            <span className={cn(met ? "text-[#25C298]" : "text-[#86909c]")}>{children}</span>
        </div>
    );
}

interface AccountInfoDialogProps {
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
    username?: string;
    avatarUrl?: string;
    onAvatarUpdated?: (url: string) => void;
}

export function AccountInfoDialog({
    open = false,
    onOpenChange,
    username = "admin",
    avatarUrl = "/path-to-avatar.png",
    onAvatarUpdated
}: AccountInfoDialogProps) {
    const localize = useLocalize();
    const [isEditing, setIsEditing] = useState(false);
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const setUser = useSetRecoilState(store.user);
    const [currentAvatarUrl, setCurrentAvatarUrl] = useState(avatarUrl);
    const fileInputRef = useRef<HTMLInputElement | null>(null);

    // 外部 avatarUrl 变化时，同步当前弹窗内展示
    useEffect(() => {
        setCurrentAvatarUrl(avatarUrl);
    }, [avatarUrl]);

    // 密码输入状态
    const [oldPassword, setOldPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");

    // 密码可见性状态
    const [showOldPassword, setShowOldPassword] = useState(false);
    const [showNewPassword, setShowNewPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);

    // 密码强度校验
    const [passwordStrength, setPasswordStrength] = useState<PasswordStrength>({
        minLength: false,
        hasAllRequired: false
    });

    // 实时校验新密码强度
    const validatePasswordStrength = (password: string) => {
        const minLength = password.length >= 8;
        const hasLower = /[a-z]/.test(password);
        const hasUpper = /[A-Z]/.test(password);
        const hasNumber = /[0-9]/.test(password);
        const hasSymbol = /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password);

        // 第二个规则要求同时包含：大写字母、小写字母、数字、特殊字符
        const hasAllRequired = hasLower && hasUpper && hasNumber && hasSymbol;

        setPasswordStrength({
            minLength,
            hasAllRequired
        });
    };

    // 处理新密码输入
    const handleNewPasswordChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const value = e.target.value;
        setNewPassword(value);
        validatePasswordStrength(value);
    };

    // 判断确认修改按钮是否可用
    const isSubmitDisabled = () => {
        if (!oldPassword || !newPassword || !confirmPassword) return true;
        if (!passwordStrength.minLength || !passwordStrength.hasAllRequired) return true;
        if (newPassword !== confirmPassword) return true;
        return false;
    };

    const publicKeyRef = useRef<string | null>(null);

    const encryptPassword = async (pwd: string) => {
        if (!pwd) return "";
        try {
            if (!publicKeyRef.current) {
                const { public_key } = await getPublicKeyApi();
                publicKeyRef.current = public_key;
            }
            const encrypt = new JSEncrypt();
            encrypt.setPublicKey(publicKeyRef.current!);
            const encrypted = encrypt.encrypt(pwd);
            return encrypted || "";
        } catch {
            return "";
        }
    };

    // 提交密码修改（对标后台 resetPwd 逻辑，先加密再提交）
    const handleSubmit = async () => {
        // 校验原密码是否为空
        if (!oldPassword) {
            showToast({
                message: localize("com_account_info_toast_enter_old_password"),
                severity: NotificationSeverity.INFO
            });
            return;
        }

        // 校验新密码是否一致
        if (newPassword !== confirmPassword) {
            showToast({
                message: localize("com_auth_password_not_match"),
                severity: NotificationSeverity.INFO
            });
            return;
        }

        try {
            const encryptedOld = await encryptPassword(oldPassword);
            const encryptedNew = await encryptPassword(newPassword);
            if (!encryptedOld || !encryptedNew) {
                showToast({
                    message: localize("com_account_info_toast_encrypt_failed"),
                    severity: NotificationSeverity.ERROR
                });
                return;
            }
            // 调用修改密码 API
            await updatePasswordApi({ oldPassword: encryptedOld, newPassword: encryptedNew });

            // 修改成功
            showToast({
                message: localize("com_account_info_toast_password_updated"),
                severity: NotificationSeverity.SUCCESS
            });

            // 重置表单
            resetForm();
            setIsEditing(false);
        } catch (error: any) {
            const codeRaw =
                error?.statusCode ??
                error?.response?.data?.status_code ??
                error?.response?.data?.code;
            const code =
                typeof codeRaw === "string" ? parseInt(codeRaw, 10) : Number(codeRaw);

            // 10603：当前密码错误（接口常以 HTTP 200 + body.status_code 返回，需在 API 层抛出后才能进此处）
            if (code === 10603) {
                showToast({
                    message: localize("com_account_info_toast_wrong_old_password"),
                    severity: NotificationSeverity.INFO
                });
                return;
            }

            const errorMessage =
                error?.response?.data?.status_message ||
                error?.response?.data?.message ||
                error?.message ||
                localize("com_account_info_toast_password_change_failed");

            const msg = String(errorMessage);

            if (
                msg.includes("原密码") ||
                msg.includes("当前密码") ||
                msg.includes("密码不正确") ||
                msg.includes("incorrect") ||
                msg.includes("Incorrect current password") ||
                msg.includes("current password")
            ) {
                showToast({
                    message: localize("com_account_info_toast_wrong_old_password"),
                    severity: NotificationSeverity.INFO
                });
            } else {
                showToast({
                    message: msg || localize("com_account_info_toast_password_change_failed"),
                    severity: NotificationSeverity.INFO
                });
            }
        }
    };

    // 取消修改
    const handleCancel = () => {
        resetForm();
        setIsEditing(false);
    };

    // 重置表单
    const resetForm = () => {
        setOldPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setShowOldPassword(false);
        setShowNewPassword(false);
        setShowConfirmPassword(false);
        setPasswordStrength({
            minLength: false,
            hasAllRequired: false
        });
    };

    // 关闭对话框时重置状态
    const handleOpenChange = (isOpen: boolean) => {
        onOpenChange?.(isOpen);
        if (!isOpen) {
            setIsEditing(false);
            resetForm();
        }
    };

    const handleAvatarClick = () => {
        fileInputRef.current?.click();
    };

    const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const allowedTypes = ["image/jpeg", "image/png", "image/webp", "image/gif"];
        if (!allowedTypes.includes(file.type)) {
            showToast({
                message: localize("com_account_info_toast_images_only"),
                severity: NotificationSeverity.WARNING
            });
            e.target.value = "";
            return;
        }

        let viewUrl: string | null = null;
        try {
            // Directly upload to backend so it returns a valid avatar URL.
            const { avatar } = await uploadUserAvatarFileApi(file);
            if (!avatar) {
                throw new Error("missing avatar url in response");
            }
            viewUrl = avatar.startsWith("/")
                ? `${__APP_ENV__.BASE_URL}${avatar}`
                : `${__APP_ENV__.BASE_URL}/${avatar}`;

            setCurrentAvatarUrl(viewUrl);
            onAvatarUpdated?.(viewUrl);
            showToast({
                message: localize("com_account_info_toast_avatar_updated"),
                severity: NotificationSeverity.SUCCESS
            });
        } catch (error) {
            console.error("upload avatar error", error);
            showToast({
                message: localize("com_account_info_toast_avatar_upload_failed"),
                severity: NotificationSeverity.ERROR
            });
        }
        // Update global user cache immediately (AuthContext uses QueryKeys.user).
        // Don't fail the whole upload flow if recoil/query cache update throws.
        try {
            if (viewUrl && typeof viewUrl === "string") {
                setUser((prev: any) => (prev ? ({ ...prev, avatar: viewUrl } as any) : prev));
            } else if (typeof __APP_ENV__ !== "undefined") {
                // fallback: do nothing; the invalidate below should refresh eventual source of truth
            }
            queryClient.invalidateQueries([QueryKeys.user]);
        } catch (err) {
            console.error("avatar sync to global state failed", err);
        } finally {
            // 允许重新选择同一个文件
            e.target.value = "";
        }
    };

    const inputClassName =
        "h-9 rounded-md border border-[#ECECEC] bg-white pr-10 text-[14px] text-[#1d2129] placeholder:text-[#c9cdd4] focus-visible:border-[#165dff] focus-visible:ring-1 focus-visible:ring-[#165dff]";

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent
                close={false}
                className="flex h-[600px] max-h-[calc(100vh-32px)] w-[600px] max-w-[calc(100vw-32px)] flex-col gap-0 overflow-hidden rounded-lg border border-[#ECECEC] bg-white p-0 shadow-[0_8px_24px_rgba(15,23,42,0.12)]"
            >
                {/* 标题栏 600×48 — 设计稿 */}
                <div className="flex h-12 w-full shrink-0 items-center justify-between px-6">
                    <h2 className="text-[16px] font-semibold leading-6 text-[#1d2129]">
                        {localize("com_account_info_title")}
                    </h2>
                    <button
                        type="button"
                        onClick={() => handleOpenChange(false)}
                        className="flex size-8 shrink-0 items-center justify-center rounded-md text-[#86909c] transition-colors hover:bg-[#f2f3f5] hover:text-[#1d2129]"
                        aria-label={localize("com_ui_close")}
                    >
                        <X className="size-4" />
                    </button>
                </div>

                {/* 内容区：552 宽、稿内约 462 高区块 + 边距，整体在 600×600 内不滚动 */}
                <div className="flex min-h-0 flex-1 flex-col overflow-hidden px-6 py-4">
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/jpeg,image/png,image/webp,image/gif"
                        className="hidden"
                        onChange={handleAvatarChange}
                    />

                    <div className="mx-auto flex w-[552px] max-w-[min(728px,100%)] flex-col gap-5">
                        <section className="flex flex-col gap-5">
                            <h3 className="text-[14px] font-semibold leading-5 text-[#212121]">
                                {localize("com_account_info_basic_info")}
                            </h3>
                            <div className="flex items-center gap-4 border-b border-[#f2f3f5] pb-3">
                                <button
                                    type="button"
                                    onClick={handleAvatarClick}
                                    title={localize("com_account_info_change_avatar")}
                                    className="group relative shrink-0 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-[#165dff] focus-visible:ring-offset-2"
                                >
                                    <Avatar className="size-14 ring-1 ring-[#f2f3f5]">
                                        {currentAvatarUrl ? <AvatarImage src={currentAvatarUrl} alt="User" /> : <AvatarName name={username} />}
                                    </Avatar>
                                    <div className="absolute inset-0 flex items-center justify-center rounded-full bg-[rgba(0,0,0,0.55)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                                        <Camera className="size-6 text-white" aria-hidden />
                                    </div>
                                </button>
                                <p className="min-w-0 text-[14px] leading-6 text-[#212121]">
                                    <span className="font-medium">{username}</span>
                                    <span>{localize("com_account_info_username_suffix")}</span>
                                </p>
                            </div>
                        </section>

                        <section className="flex flex-col gap-5">
                            <h3 className="text-[14px] font-semibold leading-5 text-[#1d2129]">
                                {localize("com_account_info_security_settings")}
                            </h3>

                            {!isEditing ? (
                                <div className="flex items-center justify-between gap-4">
                                    <div className="min-w-0">
                                        <div className="mb-1 text-[14px] text-[#86909c]">{localize("com_auth_password")}</div>
                                        <div className="text-[14px] tracking-[0.12em] text-[#1d2129]">
                                            ••••••••••••••••
                                        </div>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() => setIsEditing(true)}
                                        className="h-8 shrink-0 rounded-md border border-[#e5e6eb] bg-white px-4 text-[14px] text-[#1d2129] transition-colors hover:bg-[#f7f8fa]"
                                    >
                                        {localize("com_account_info_edit")}
                                    </button>
                                </div>
                            ) : (
                                <div className="flex flex-col gap-5">
                                    <div>
                                        <label className="mb-1 block text-[14px] text-[#4e5969]" htmlFor="account-old-pwd">
                                            {localize("com_account_info_old_password")}
                                        </label>
                                        <div className="relative">
                                            <Input
                                                id="account-old-pwd"
                                                type={showOldPassword ? "text" : "password"}
                                                value={oldPassword}
                                                onChange={(e) => setOldPassword(e.target.value)}
                                                placeholder={localize("com_account_info_placeholder_old_password")}
                                                className={inputClassName}
                                            />
                                            <button
                                                type="button"
                                                onClick={() => setShowOldPassword(!showOldPassword)}
                                                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909c] hover:text-[#4e5969]"
                                            >
                                                {showOldPassword ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
                                            </button>
                                        </div>
                                    </div>

                                    <div>
                                        <label className="mb-1 block text-[14px] text-[#4e5969]" htmlFor="account-new-pwd">
                                            {localize("com_account_info_new_password")}
                                        </label>
                                        <div className="relative">
                                            <Input
                                                id="account-new-pwd"
                                                type={showNewPassword ? "text" : "password"}
                                                value={newPassword}
                                                onChange={handleNewPasswordChange}
                                                placeholder={localize("com_account_info_placeholder_new_password")}
                                                className={inputClassName}
                                            />
                                            <button
                                                type="button"
                                                onClick={() => setShowNewPassword(!showNewPassword)}
                                                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909c] hover:text-[#4e5969]"
                                            >
                                                {showNewPassword ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
                                            </button>
                                        </div>

                                        <div className="mt-2 flex flex-col gap-1.5">
                                            <p className="text-[12px] text-[#86909c]">{localize("com_account_info_password_strength")}</p>
                                            <PasswordStrengthRow met={passwordStrength.minLength}>
                                                {localize("com_account_info_password_rule_min")}
                                            </PasswordStrengthRow>
                                            <PasswordStrengthRow met={passwordStrength.hasAllRequired}>
                                                {localize("com_account_info_password_rule_complex")}
                                            </PasswordStrengthRow>
                                        </div>
                                    </div>

                                    <div>
                                        <label className="mb-1 block text-[14px] text-[#4e5969]" htmlFor="account-confirm-pwd">
                                            {localize("com_auth_password_confirm")}
                                        </label>
                                        <div className="relative">
                                            <Input
                                                id="account-confirm-pwd"
                                                type={showConfirmPassword ? "text" : "password"}
                                                value={confirmPassword}
                                                onChange={(e) => setConfirmPassword(e.target.value)}
                                                placeholder={localize("com_account_info_placeholder_confirm_password")}
                                                className={inputClassName}
                                            />
                                            <button
                                                type="button"
                                                onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                                                className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909c] hover:text-[#4e5969]"
                                            >
                                                {showConfirmPassword ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
                                            </button>
                                        </div>
                                    </div>

                                    <div className="flex items-center justify-end gap-4">
                                        <button
                                            type="button"
                                            onClick={handleCancel}
                                            className="text-[14px] text-[#4e5969] transition-colors hover:text-[#1d2129]"
                                        >
                                            {localize("cancel")}
                                        </button>
                                        <Button
                                            type="button"
                                            onClick={handleSubmit}
                                            disabled={isSubmitDisabled()}
                                            className={cn(
                                                "h-9 rounded-md px-5 text-[14px] font-normal text-white disabled:opacity-100",
                                                isSubmitDisabled()
                                                    ? "cursor-not-allowed bg-[#7399E4] hover:bg-[#7399E4]"
                                                    : "bg-[#0253E8] hover:bg-[#0246cc]"
                                            )}
                                        >
                                            {localize("com_account_info_confirm_change")}
                                        </Button>
                                    </div>
                                </div>
                            )}
                        </section>
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
