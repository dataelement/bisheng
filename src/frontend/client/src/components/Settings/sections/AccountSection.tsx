import { useEffect, useRef, useState } from "react";
import { Camera } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { uploadUserAvatarFileApi } from "~/api/user";
import { NotificationSeverity } from "~/common";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
// Moved verbatim from the retired AccountInfoDialog — store.user is a frozen legacy atom (ledger #5), no new atoms added.
// eslint-disable-next-line no-restricted-imports
import { useSetRecoilState } from "recoil";
import store from "~/store";
import { QueryKeys } from "~/types/chat";
import { PasswordForm } from "./PasswordForm";

export interface AccountSectionProps {
    username: string;
    avatarUrl: string;
    onAvatarUpdated?: (url: string) => void;
}

/** Basic info (avatar + username) and security settings (password), formerly AccountInfoDialog. */
export function AccountSection({ username, avatarUrl, onAvatarUpdated }: AccountSectionProps) {
    const localize = useLocalize();
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const setUser = useSetRecoilState(store.user);
    const [isEditing, setIsEditing] = useState(false);
    const [currentAvatarUrl, setCurrentAvatarUrl] = useState(avatarUrl);
    const fileInputRef = useRef<HTMLInputElement | null>(null);

    // Keep the in-dialog avatar in sync when the caller updates it
    useEffect(() => {
        setCurrentAvatarUrl(avatarUrl);
    }, [avatarUrl]);

    const handleAvatarChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const allowedTypes = ["image/jpeg", "image/png", "image/webp", "image/gif"];
        if (!allowedTypes.includes(file.type)) {
            showToast({
                message: localize("com_account_info_toast_images_only"),
                severity: NotificationSeverity.WARNING,
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
                severity: NotificationSeverity.SUCCESS,
            });
        } catch (error) {
            console.error("upload avatar error", error);
            showToast({
                message: localize("com_account_info_toast_avatar_upload_failed"),
                severity: NotificationSeverity.ERROR,
            });
        }
        // Update global user cache immediately (AuthContext uses QueryKeys.user).
        // Don't fail the whole upload flow if state/query cache update throws.
        try {
            if (viewUrl && typeof viewUrl === "string") {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                setUser((prev: any) => (prev ? ({ ...prev, avatar: viewUrl } as any) : prev));
            }
            queryClient.invalidateQueries([QueryKeys.user]);
        } catch (err) {
            console.error("avatar sync to global state failed", err);
        } finally {
            // Allow picking the same file again
            e.target.value = "";
        }
    };

    return (
        <div className="flex flex-col gap-5">
            <input
                ref={fileInputRef}
                type="file"
                accept="image/jpeg,image/png,image/webp,image/gif"
                className="hidden"
                onChange={handleAvatarChange}
            />

            <section className="flex flex-col gap-4">
                <h3 className="text-[14px] font-semibold leading-5 text-[#212121]">
                    {localize("com_account_info_basic_info")}
                </h3>
                <div className="flex items-center gap-4 border-b border-[#f2f3f5] pb-4">
                    <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        title={localize("com_account_info_change_avatar")}
                        className="group relative shrink-0 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
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

            <section className="flex flex-col gap-4">
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
                    <PasswordForm onCancel={() => setIsEditing(false)} onSuccess={() => setIsEditing(false)} />
                )}
            </section>
        </div>
    );
}
