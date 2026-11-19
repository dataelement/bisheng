import { useEffect, useRef, useState } from "react";
import { Camera } from "lucide-react";
import { Outlined } from 'bisheng-icons';
import { useQueryClient } from "@tanstack/react-query";
import { Button, Tooltip } from '@bisheng/ui';
import { uploadUserAvatarFileApi, type NicknameProfile } from "~/api/user";
import { NotificationSeverity } from "~/common";
import { Avatar, AvatarImage, AvatarName } from "~/components/ui/Avatar";
import { useLocalize } from "~/hooks";
import { useToastContext } from "~/Providers";
// Moved verbatim from the retired AccountInfoDialog — store.user is a frozen legacy atom (ledger #5), no new atoms added.
// eslint-disable-next-line no-restricted-imports
import { useSetRecoilState } from "recoil";
import store from "~/store";
import { QueryKeys } from "~/types/chat";
import type { TUser } from '~/types/chat';
import { PasswordForm } from "./PasswordForm";
import { NicknameEditor } from './NicknameEditor';
import { copyText } from '~/utils';

const accountFieldLabelClassName = 'mb-1 text-[14px] text-[#86909c]';
// Offset the small button's 5px icon inset to keep 8px of visual spacing.
const inlineActionClassName = '-ms-[0.3125rem] shrink-0 text-text-3';

export interface AccountSectionProps {
    username: string;
    account?: string | null;
    avatarUrl: string;
    onAvatarUpdated?: (url: string) => void;
}

/** Basic info (avatar + username) and security settings (password), formerly AccountInfoDialog. */
export function AccountSection({ username, account, avatarUrl, onAvatarUpdated }: AccountSectionProps) {
    const localize = useLocalize();
    const editNicknameLabel = localize('accountIdentity.editNickname');
    const copyAccountLabel = localize('accountIdentity.copyAccount');
    const { showToast } = useToastContext();
    const queryClient = useQueryClient();
    const setUser = useSetRecoilState(store.user);
    const [isEditing, setIsEditing] = useState(false);
    const [isEditingNickname, setIsEditingNickname] = useState(false);
    const [currentNickname, setCurrentNickname] = useState(username);
    const [currentAvatarUrl, setCurrentAvatarUrl] = useState(avatarUrl);
    const fileInputRef = useRef<HTMLInputElement | null>(null);
    const handleCopyAccount = async () => {
        if (!account) return;
        try {
            await copyText(account);
            showToast({ message: localize('accountIdentity.accountCopied'), severity: NotificationSeverity.SUCCESS });
        } catch {
            showToast({ message: localize('accountIdentity.copyFailed'), severity: NotificationSeverity.WARNING });
        }
    };
    useEffect(() => { setCurrentNickname(username); }, [username]);

    const handleNicknameSaved = (profile: NicknameProfile) => {
        setCurrentNickname(profile.user_name);
        setIsEditingNickname(false);
        const update = (previous: TUser) => String(previous.id) === String(profile.user_id)
            ? { ...previous, username: profile.user_name, name: profile.user_name, external_id: profile.external_id }
            : previous;
        setUser(previous => previous ? update(previous) : previous);
        queryClient.setQueryData<TUser>([QueryKeys.user], previous => previous ? update(previous) : previous);
        // Refresh is optional after the committed result is already visible.
        void queryClient.invalidateQueries({ queryKey: [QueryKeys.user] }).catch((error: unknown) => {
            console.warn('Account refresh after nickname update failed', error instanceof Error ? error.name : typeof error);
        });
        showToast({ message: localize('accountIdentity.nicknameSaved'), severity: NotificationSeverity.SUCCESS });
    };

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
                severity: NotificationSeverity.WARNING,
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
                <div className="flex items-start gap-4 pb-4">
                    <button
                        type="button"
                        onClick={() => fileInputRef.current?.click()}
                        title={localize("com_account_info_change_avatar")}
                        className="group relative shrink-0 rounded-full outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2"
                    >
                        <Avatar className="size-14 ring-1 ring-[#f2f3f5]">
                            {currentAvatarUrl ? <AvatarImage src={currentAvatarUrl} alt="User" /> : <AvatarName name={currentNickname} />}
                        </Avatar>
                        <div className="absolute inset-0 flex items-center justify-center rounded-full bg-[rgba(0,0,0,0.55)] opacity-0 transition-opacity group-hover:opacity-100 group-focus-visible:opacity-100">
                            <Camera className="size-6 text-white" aria-hidden />
                        </div>
                    </button>
                    <dl className="min-w-0 flex-1 pt-1">
                        <dt className={accountFieldLabelClassName}>{localize('accountIdentity.nickname')}</dt>
                        <dd className="grid grid-cols-1">
                            {/* Reserve the editor's height even when its actions wrap onto another line. */}
                            <div className="col-start-1 row-start-1 aria-hidden:invisible" aria-hidden={!isEditingNickname}>
                                <NicknameEditor
                                    key={isEditingNickname ? 'editing' : 'display'}
                                    nickname={currentNickname}
                                    autoFocus={isEditingNickname}
                                    onCancel={() => setIsEditingNickname(false)}
                                    onSaved={handleNicknameSaved}
                                />
                            </div>
                            {!isEditingNickname && (
                                <div className="col-start-1 row-start-1 flex min-h-8 items-center gap-2 self-start">
                                    <span className="min-w-0 truncate text-body text-text-1" title={currentNickname}>{currentNickname}</span>
                                    <Tooltip content={editNicknameLabel}>
                                        <Button
                                            type="button"
                                            size="small"
                                            variant="text"
                                            color="default"
                                            iconOnly
                                            aria-label={editNicknameLabel}
                                            className={inlineActionClassName}
                                            onClick={() => setIsEditingNickname(true)}
                                        >
                                            <Outlined.Edit aria-hidden />
                                        </Button>
                                    </Tooltip>
                                </div>
                            )}
                        </dd>
                    </dl>
                </div>
                <dl className="min-w-0 pb-5">
                    <dt className={accountFieldLabelClassName}>{localize('accountIdentity.account')}</dt>
                    <dd className="flex items-center gap-2">
                        <span className="min-w-0 whitespace-pre-wrap break-words text-body text-text-1">
                            {account || localize('accountIdentity.noAccount')}
                        </span>
                        <Tooltip content={copyAccountLabel}>
                            <Button
                                type="button"
                                size="small"
                                variant="text"
                                color="default"
                                iconOnly
                                disabled={!account}
                                aria-label={copyAccountLabel}
                                className={inlineActionClassName}
                                onClick={() => void handleCopyAccount()}
                            >
                                <Outlined.Copy aria-hidden />
                            </Button>
                        </Tooltip>
                    </dd>
                </dl>
            </section>

            <section className="flex flex-col gap-4">
                {!isEditing ? (
                    <div className="flex items-center justify-between gap-4">
                        <div className="min-w-0">
                            <div className={accountFieldLabelClassName}>{localize("com_auth_password")}</div>
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
