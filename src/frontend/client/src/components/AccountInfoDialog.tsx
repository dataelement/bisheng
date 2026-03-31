import { useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSetRecoilState } from "recoil";
import { X, Eye, EyeOff, Check, Camera } from "lucide-react";
import { Avatar, AvatarImage } from "~/components/ui/Avatar";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { Dialog, DialogContent } from "~/components/ui/Dialog";
import { useToastContext } from "~/Providers";
import { NotificationSeverity } from "~/common";
import { updatePasswordApi, uploadUserAvatarFileApi, getPublicKeyApi } from "~/api/user";
import { JSEncrypt } from 'jsencrypt';
import store from "~/store";
import { QueryKeys } from "~/types/chat";


interface PasswordStrength {
    minLength: boolean;
    hasAllRequired: boolean;
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
                message: "请输入原密码",
                severity: NotificationSeverity.INFO
            });
            return;
        }

        // 校验新密码是否一致
        if (newPassword !== confirmPassword) {
            showToast({
                message: "新密码两次输入不一致",
                severity: NotificationSeverity.INFO
            });
            return;
        }

        try {
            const encryptedOld = await encryptPassword(oldPassword);
            const encryptedNew = await encryptPassword(newPassword);
            if (!encryptedOld || !encryptedNew) {
                showToast({
                    message: "密码加密失败，请稍后重试",
                    severity: NotificationSeverity.ERROR
                });
                return;
            }
            // 调用修改密码 API
            await updatePasswordApi({ oldPassword: encryptedOld, newPassword: encryptedNew });

            // 修改成功
            showToast({
                message: "密码已修改",
                severity: NotificationSeverity.SUCCESS
            });

            // 重置表单
            resetForm();
            setIsEditing(false);
        } catch (error: any) {
            // 处理错误响应
            const errorMessage = error?.response?.data?.message || error?.message || "密码修改失败";

            // 根据错误信息判断是否是原密码错误
            if (errorMessage.includes("原密码") || errorMessage.includes("密码不正确") || errorMessage.includes("incorrect")) {
                showToast({
                    message: "原密码不正确，请重新输入",
                    severity: NotificationSeverity.INFO
                });
            } else {
                showToast({
                    message: errorMessage,
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
                message: "仅支持上传图片文件",
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
                message: "头像更新成功",
                severity: NotificationSeverity.SUCCESS
            });
        } catch (error) {
            console.error("upload avatar error", error);
            showToast({
                message: "头像上传失败，请重试",
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

    return (
        <Dialog open={open} onOpenChange={handleOpenChange}>
            <DialogContent className="w-[480px] p-0 rounded-2xl shadow-[0_8px_24px_rgba(0,0,0,0.12)]">
                {/* 标题栏 */}
                <div className="flex items-center justify-between px-6 py-4 border-b border-[#f2f3f5]">
                    <h2 className="text-[16px] font-semibold text-[#1d2129]">账号信息</h2>
                </div>

                {/* 内容区域 */}
                <div className="px-6 py-5 space-y-5 -mt-10">
                    {/* 隐藏的头像上传 input */}
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept="image/jpeg,image/png,image/webp,image/gif"
                        className="hidden"
                        onChange={handleAvatarChange}
                    />
                    {/* 基本信息 */}
                    <div>
                        <h3 className="text-[14px] font-medium text-[#1d2129] mb-3">基本信息</h3>
                        <div className="flex items-center gap-3 p-3 bg-[#f7f8fa] rounded-lg">
                            <button
                                type="button"
                                onClick={handleAvatarClick}
                                title="更换头像"
                                className="relative group rounded-full shrink-0 outline-none focus-visible:ring-2 focus-visible:ring-[#165dff] focus-visible:ring-offset-2"
                            >
                                <Avatar className="size-12">
                                    <AvatarImage src={currentAvatarUrl} alt={username} />
                                </Avatar>
                                <div className="absolute inset-0 rounded-full bg-[rgba(0,0,0,0.45)] opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 flex flex-col items-center justify-center gap-0.5 text-white transition-opacity px-1">
                                    <Camera className="size-3.5 shrink-0" aria-hidden />
                                    <span className="text-[10px] leading-tight text-center">
                                        更换
                                        <br />
                                        头像
                                    </span>
                                </div>
                            </button>
                            <div className="flex items-center text-[14px]">
                                <span className="text-[#1d2129] font-medium">{username}</span>
                                <span className="text-[#86909c] ml-1">(用户名)</span>
                            </div>
                        </div>
                    </div>

                    {/* 安全设置 */}
                    <div>
                        <h3 className="text-[14px] font-medium text-[#1d2129] mb-3">安全设置</h3>

                        {!isEditing ? (
                            /* 密码显示状态 */
                            <div className="flex items-center justify-between p-3 bg-[#f7f8fa] rounded-lg">
                                <div className="flex items-center gap-2">
                                    <span className="text-[14px] text-[#4e5969]">密码</span>
                                    <span className="text-[14px] text-[#1d2129]">••••••••••••</span>
                                </div>
                                <button
                                    onClick={() => setIsEditing(true)}
                                    className="text-[14px] text-[#165dff] hover:text-[#4080ff] transition-colors"
                                >
                                    修改
                                </button>
                            </div>
                        ) : (
                            /* 修改密码表单 */
                            <div className="space-y-4">
                                {/* 原密码 */}
                                <div>
                                    <label className="block text-[14px] text-[#4e5969] mb-2">原密码</label>
                                    <div className="relative">
                                        <Input
                                            type={showOldPassword ? "text" : "password"}
                                            value={oldPassword}
                                            onChange={(e) => setOldPassword(e.target.value)}
                                            placeholder="请输入原密码"
                                            className="pr-10 h-9 text-[14px] bg-white border-[#e5e6eb] focus:border-[#165dff] focus:ring-1 focus:ring-[#165dff]"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowOldPassword(!showOldPassword)}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909c] hover:text-[#4e5969]"
                                        >
                                            {showOldPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                                        </button>
                                    </div>
                                </div>

                                {/* 新密码 */}
                                <div>
                                    <label className="block text-[14px] text-[#4e5969] mb-2">新密码</label>
                                    <div className="relative">
                                        <Input
                                            type={showNewPassword ? "text" : "password"}
                                            value={newPassword}
                                            onChange={handleNewPasswordChange}
                                            placeholder="请输入新密码"
                                            className="pr-10 h-9 text-[14px] bg-white border-[#e5e6eb] focus:border-[#165dff] focus:ring-1 focus:ring-[#165dff]"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowNewPassword(!showNewPassword)}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909c] hover:text-[#4e5969]"
                                        >
                                            {showNewPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                                        </button>
                                    </div>

                                    {/* 密码强度提示 */}
                                    <div className="mt-2 space-y-1">
                                        <div className={`flex items-center gap-1.5 text-[12px] transition-colors ${passwordStrength.minLength ? 'text-[#00b42a]' : 'text-[#86909c]'
                                            }`}>
                                            <Check className={`size-3 ${passwordStrength.minLength ? 'opacity-100' : 'opacity-30'
                                                }`} />
                                            <span>至少 8 个字符</span>
                                        </div>
                                        <div className={`flex items-center gap-1.5 text-[12px] transition-colors ${passwordStrength.hasAllRequired ? 'text-[#00b42a]' : 'text-[#86909c]'
                                            }`}>
                                            <Check className={`size-3 ${passwordStrength.hasAllRequired ? 'opacity-100' : 'opacity-30'
                                                }`} />
                                            <span>包含大小写字母、数字和字符</span>
                                        </div>
                                    </div>
                                </div>

                                {/* 确认密码 */}
                                <div>
                                    <label className="block text-[14px] text-[#4e5969] mb-2">确认密码</label>
                                    <div className="relative">
                                        <Input
                                            type={showConfirmPassword ? "text" : "password"}
                                            value={confirmPassword}
                                            onChange={(e) => setConfirmPassword(e.target.value)}
                                            placeholder="请再次输入新密码"
                                            className="pr-10 h-9 text-[14px] bg-white border-[#e5e6eb] focus:border-[#165dff] focus:ring-1 focus:ring-[#165dff]"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowConfirmPassword(!showConfirmPassword)}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909c] hover:text-[#4e5969]"
                                        >
                                            {showConfirmPassword ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
                                        </button>
                                    </div>
                                </div>

                                {/* 按钮组 */}
                                <div className="flex items-center justify-end gap-3 pt-2">
                                    <Button
                                        variant="outline"
                                        onClick={handleCancel}
                                        className="h-8 px-4 text-[14px] text-[#4e5969] border-[#e5e6eb] hover:bg-[#f7f8fa]"
                                    >
                                        取消
                                    </Button>
                                    <Button
                                        onClick={handleSubmit}
                                        disabled={isSubmitDisabled()}
                                        className={`h-8 px-4 text-[14px] ${isSubmitDisabled()
                                            ? 'bg-[#e5e6eb] text-[#c9cdd4] cursor-not-allowed hover:bg-[#e5e6eb]'
                                            : 'bg-[#165dff] text-white hover:bg-[#4080ff]'
                                            }`}
                                    >
                                        确认修改
                                    </Button>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </DialogContent>
        </Dialog>
    );
}
