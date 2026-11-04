import { Button, Input } from '@bisheng/ui';
import { Outlined } from "bisheng-icons";



import { userContext } from "@/contexts/userContext";
import { useDshBrowserConfig } from "@/hooks/useDshBrowserConfig";
import { useDshProfile } from "@/hooks/useDshProfile";
import { copyText } from "@/utils";
import { dshLaunchUrl } from "@/utils/dshLaunch";
import { rememberDesktopLoginReturnTo } from "@/utils/loginReturnTo";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { callbackUrl, readAuthId, useDshAuthorization } from "./useDshAuthorization";

export function DshLogin() {
    const { t } = useTranslation();
    const { user } = useContext(userContext);
    const { config, failed } = useDshBrowserConfig();
    const homeUrl = import.meta.env.BASE_URL;
    const [copyStatus, setCopyStatus] = useState<"idle" | "copied" | "failed">("idle");
    useEffect(() => {
        const previous = document.title;
        document.title = t("dsh.title");
        return () => {
            document.title = previous;
        };
    }, [t]);
    let authId: string | null = null;
    let invalid = false;
    try {
        authId = readAuthId(location.search);
    } catch {
        invalid = true;
    }
    const flow = useDshAuthorization(authId);
    useEffect(() => {
        const meta = document.createElement("meta");
        meta.name = "referrer";
        meta.content = "no-referrer";
        document.head.appendChild(meta);
        return () => {
            meta.remove();
        };
    }, []);
    function handleLogin() {
        rememberDesktopLoginReturnTo();
        location.assign(homeUrl);
    }
    async function handleCopy(value: string) {
        setCopyStatus("idle");
        try {
            await copyText(value);
            setCopyStatus("copied");
        } catch {
            setCopyStatus("failed");
        }
    }
    const profile = useDshProfile(user?.user_id, !!config?.enabled);
    const departmentName = profile?.department_name?.trim();
    const base = location.origin;
    const download = config?.download_url;
    const completed = !invalid && !failed && config?.enabled && !!user?.user_id && flow.status === "issued";
    return (
        <main className="flex min-h-screen items-center justify-center bg-background p-4">
            <section className="flex w-full max-w-xl flex-col gap-5 rounded-2xl border bg-background p-6 shadow-sm sm:p-8">
                {completed ? (
                    <header role="status" aria-live="polite" className="flex flex-col items-center gap-3 text-center">
                        <p className="text-sm font-medium text-muted-foreground">{t("dsh.title")}</p>
                        <div className="mt-2 flex h-14 w-14 items-center justify-center rounded-full bg-green-50 text-green-600 dark:bg-green-950">
                            <Outlined.CheckCircle aria-hidden className="h-8 w-8" />
                        </div>
                        <h1 className="text-2xl font-semibold tracking-tight">{t("dsh.authorizationComplete")}</h1>
                        <p className="text-sm leading-6 text-muted-foreground">{t("dsh.authorizationCompleteHelp")}</p>
                        <p className="text-sm font-medium">
                            {user.user_name}
                            {departmentName && ` · ${departmentName}`}
                        </p>
                    </header>
                ) : (
                    <>
                        <h1 className="text-xl font-semibold">{t("dsh.title")}</h1>
                        <p className="break-all text-sm text-muted-foreground">{base}</p>
                    </>
                )}
                {invalid || failed ? (
                    <p role="alert">{t("dsh.unavailable")}</p>
                ) : !config ? (
                    <p role="status">{t("dsh.loading")}</p>
                ) : !config.enabled ? (
                    <p role="status">{t("dsh.disabled")}</p>
                ) : (
                    <>
                        {!authId ? (
                            <>
                                <p>{t("dsh.entryHelp")}</p>
                                <Button onClick={() => location.assign(dshLaunchUrl(config.launch_url))}>
                                    {t("dsh.openDesktop")}
                                </Button>
                                <p className="text-sm text-muted-foreground">{t("dsh.installHelp")}</p>
                                {download && (
                                    <Button variant="outlined" asChild color="default">
                                        <a href={download} target="_blank" rel="noreferrer">
                                            {t("dsh.download")}
                                        </a>
                                    </Button>
                                )}
                                <Input aria-label={t("dsh.server")} readOnly value={base} />
                                <Button variant="outlined" onClick={() => handleCopy(base)} color="default">
                                    {t("dsh.copyServer")}
                                </Button>
                            </>
                        ) : !user?.user_id ? (
                            <Button onClick={handleLogin}>{t("dsh.login")}</Button>
                        ) : (
                            <>
                                {!completed && (
                                    <p>
                                        {t(
                                            departmentName
                                                ? "dsh.authorizeWithDepartment"
                                                : "dsh.authorize_without_tenant",
                                            {
                                                name: user.user_name,
                                                department: departmentName,
                                            },
                                        )}
                                    </p>
                                )}
                                {flow.status === "idle" && (
                                    <div className="flex flex-wrap gap-2">
                                        <Button onClick={flow.handleAuthorize}>{t("dsh.authorize")}</Button>
                                        <Button variant="outlined" onClick={flow.handleCancel} color="default">
                                            {t("dsh.cancel")}
                                        </Button>
                                    </div>
                                )}
                                {!completed && (
                                    <p role="status">{flow.status !== "idle" && t(`dsh.auth_${flow.status}`)}</p>
                                )}
                                {flow.status === "issued" && (
                                    <Button className="w-full" onClick={() => location.assign(dshLaunchUrl(config.launch_url))}>
                                        {t("dsh.returnDesktop")}
                                        <Outlined.ArrowRightUp aria-hidden className="h-4 w-4" />
                                    </Button>
                                )}
                                {flow.denialUrl && (
                                    <iframe
                                        title={t("dsh.callback")}
                                        className="hidden"
                                        referrerPolicy="no-referrer"
                                        src={flow.denialUrl}
                                    />
                                )}
                                {flow.authorization && (
                                    <>
                                        <iframe
                                            title={t("dsh.callback")}
                                            className="hidden"
                                            referrerPolicy="no-referrer"
                                            src={callbackUrl(authId, flow.authorization)}
                                        />
                                        <details className="rounded-lg border border-dashed p-4 text-sm">
                                            <summary className="cursor-pointer text-muted-foreground">
                                                {t("dsh.manualLoginFallback")}
                                            </summary>
                                            <div className="mt-4 flex flex-col gap-3">
                                                <p className="leading-6 text-muted-foreground">{t("dsh.ticketHelp")}</p>
                                                <Input type="password" autoComplete="off" aria-label={t("dsh.ticket")} readOnly value={flow.authorization.identity_ticket} />
                                                <Button variant="outlined" onClick={() => handleCopy(flow.authorization!.identity_ticket)} color="default">
                                                    {t("dsh.copyTicket")}
                                                </Button>
                                            </div>
                                        </details>
                                    </>
                                )}
                            </>
                        )}
                        {copyStatus === "copied" && <p role="status">{t("dsh.copied")}</p>}
                        {copyStatus === "failed" && <p role="alert">{t("dsh.copyFailed")}</p>}
                    </>
                )}
                {completed && (
                    <p className="break-all border-t pt-4 text-center text-xs text-muted-foreground">{base}</p>
                )}
            </section>
        </main>
    );
}
