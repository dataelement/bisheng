import { useRef, useState, type ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";
import { JSEncrypt } from "jsencrypt";
import { getPublicKeyApi, updatePasswordApi } from "~/api/user";
import { NotificationSeverity } from "~/common";
import { Button } from "~/components/ui/Button";
import { Input } from "~/components/ui/Input";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
import { cn } from "~/utils";

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

/* eslint-disable no-restricted-syntax -- matches backend error copy (both languages), not UI text */
const WRONG_OLD_PASSWORD_PATTERNS = [
    "原密码",
    "当前密码",
    "密码不正确",
    "incorrect",
    "Incorrect current password",
    "current password",
];
/* eslint-enable no-restricted-syntax */

const inputClassName =
    "h-9 rounded-md border border-[#ECECEC] bg-white pr-10 text-[14px] text-[#1d2129] placeholder:text-[#c9cdd4] focus-visible:border-[#DDDDDD] focus-visible:ring-2 focus-visible:ring-[#F1F5F9]";

interface PasswordFieldProps {
    id: string;
    label: string;
    value: string;
    placeholder: string;
    visible: boolean;
    onToggleVisible: () => void;
    onChange: (value: string) => void;
}

function PasswordField({ id, label, value, placeholder, visible, onToggleVisible, onChange }: PasswordFieldProps) {
    return (
        <div>
            <label className="mb-1 block text-[14px] text-[#4e5969]" htmlFor={id}>
                {label}
            </label>
            <div className="relative">
                <Input
                    id={id}
                    type={visible ? "text" : "password"}
                    value={value}
                    onChange={(e) => onChange(e.target.value)}
                    placeholder={placeholder}
                    className={inputClassName}
                />
                <button
                    type="button"
                    onClick={onToggleVisible}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-[#86909c] hover:text-[#4e5969]"
                >
                    {visible ? <Eye className="size-4" /> : <EyeOff className="size-4" />}
                </button>
            </div>
        </div>
    );
}

export interface PasswordFormProps {
    onCancel: () => void;
    onSuccess: () => void;
}

/** Change-password form (RSA-encrypted submit), extracted from the retired AccountInfoDialog. */
export function PasswordForm({ onCancel, onSuccess }: PasswordFormProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();

    const [oldPassword, setOldPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [showOldPassword, setShowOldPassword] = useState(false);
    const [showNewPassword, setShowNewPassword] = useState(false);
    const [showConfirmPassword, setShowConfirmPassword] = useState(false);
    const [passwordStrength, setPasswordStrength] = useState<PasswordStrength>({
        minLength: false,
        hasAllRequired: false,
    });

    const handleNewPasswordChange = (value: string) => {
        setNewPassword(value);
        const hasLower = /[a-z]/.test(value);
        const hasUpper = /[A-Z]/.test(value);
        const hasNumber = /[0-9]/.test(value);
        const hasSymbol = /[!@#$%^&*()_+\-=[\]{};':"\\|,.<>/?]/.test(value);
        setPasswordStrength({
            minLength: value.length >= 8,
            hasAllRequired: hasLower && hasUpper && hasNumber && hasSymbol,
        });
    };

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

    // Submit the password change (mirror backend resetPwd flow: encrypt first, then submit)
    const handleSubmit = async () => {
        if (!oldPassword) {
            showToast({
                message: localize("com_account_info_toast_enter_old_password"),
                severity: NotificationSeverity.INFO,
            });
            return;
        }
        if (newPassword !== confirmPassword) {
            showToast({
                message: localize("com_auth_password_not_match"),
                severity: NotificationSeverity.INFO,
            });
            return;
        }

        try {
            const encryptedOld = await encryptPassword(oldPassword);
            const encryptedNew = await encryptPassword(newPassword);
            if (!encryptedOld || !encryptedNew) {
                showToast({
                    message: localize("com_account_info_toast_encrypt_failed"),
                    severity: NotificationSeverity.ERROR,
                });
                return;
            }
            await updatePasswordApi({ oldPassword: encryptedOld, newPassword: encryptedNew });
            showToast({
                message: localize("com_account_info_toast_password_updated"),
                severity: NotificationSeverity.SUCCESS,
            });
            onSuccess();
        } catch (rawError) {
            // Error shape varies by request layer (axios error vs rethrown body); narrow manually.
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const error = rawError as any;
            const codeRaw =
                error?.statusCode ??
                error?.response?.data?.status_code ??
                error?.response?.data?.code;
            const code = typeof codeRaw === "string" ? parseInt(codeRaw, 10) : Number(codeRaw);

            // 10603: wrong current password (the API often replies HTTP 200 + body.status_code;
            // it only lands here after the request layer rethrows it)
            if (code === 10603) {
                showToast({
                    message: localize("com_account_info_toast_wrong_old_password"),
                    severity: NotificationSeverity.INFO,
                });
                return;
            }

            // 10622: password strength rejected by the backend; localized copy
            if (code === 10622) {
                showToast({
                    message: localize("api_errors.10622"),
                    severity: NotificationSeverity.ERROR,
                });
                return;
            }

            const errorMessage =
                error?.response?.data?.status_message ||
                error?.response?.data?.message ||
                error?.message ||
                localize("com_account_info_toast_password_change_failed");
            const msg = String(errorMessage);

            if (WRONG_OLD_PASSWORD_PATTERNS.some((pattern) => msg.includes(pattern))) {
                showToast({
                    message: localize("com_account_info_toast_wrong_old_password"),
                    severity: NotificationSeverity.INFO,
                });
            } else {
                showToast({
                    message: msg || localize("com_account_info_toast_password_change_failed"),
                    severity: NotificationSeverity.INFO,
                });
            }
        }
    };

    return (
        <div className="flex flex-col gap-5">
            <PasswordField
                id="account-old-pwd"
                label={localize("com_account_info_old_password")}
                value={oldPassword}
                placeholder={localize("com_account_info_placeholder_old_password")}
                visible={showOldPassword}
                onToggleVisible={() => setShowOldPassword((v) => !v)}
                onChange={setOldPassword}
            />

            <div>
                <PasswordField
                    id="account-new-pwd"
                    label={localize("com_account_info_new_password")}
                    value={newPassword}
                    placeholder={localize("com_account_info_placeholder_new_password")}
                    visible={showNewPassword}
                    onToggleVisible={() => setShowNewPassword((v) => !v)}
                    onChange={handleNewPasswordChange}
                />
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

            <PasswordField
                id="account-confirm-pwd"
                label={localize("com_auth_password_confirm")}
                value={confirmPassword}
                placeholder={localize("com_account_info_placeholder_confirm_password")}
                visible={showConfirmPassword}
                onToggleVisible={() => setShowConfirmPassword((v) => !v)}
                onChange={setConfirmPassword}
            />

            {/* Desktop: right-aligned compact actions; mobile: full-width pair */}
            <div className="mt-1 flex items-center justify-end gap-4 touch-mobile:gap-3">
                <button
                    type="button"
                    onClick={onCancel}
                    className="h-8 rounded-md border border-[#e5e6eb] bg-white px-4 text-[14px] font-normal text-[#4e5969] transition-colors hover:bg-[#f7f8fa] hover:text-[#1d2129] touch-mobile:h-11 touch-mobile:flex-1 touch-mobile:rounded-lg touch-mobile:text-[15px]"
                >
                    {localize("cancel")}
                </button>
                <Button
                    type="button"
                    onClick={handleSubmit}
                    disabled={isSubmitDisabled()}
                    className={cn(
                        "h-8 rounded-md px-4 text-[14px] font-normal text-white disabled:opacity-100 touch-mobile:h-11 touch-mobile:flex-1 touch-mobile:rounded-lg touch-mobile:text-[15px]",
                        isSubmitDisabled()
                            ? "cursor-not-allowed bg-blue-300 hover:bg-blue-300"
                            : "bg-blue-600 hover:bg-blue-700 btn-brand-primary",
                    )}
                >
                    {localize("com_account_info_confirm_change")}
                </Button>
            </div>
        </div>
    );
}
