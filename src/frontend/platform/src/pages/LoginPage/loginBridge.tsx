import { Button } from '@bisheng/ui';
import { claimKunlianWorkflowLoginAttempt, parseKunlianWorkflowEntry } from '@bisheng/api-client';
import Separator from "@/components/bs-comp/chatComponent/Separator";
import { buildKunlianLoginUrl } from '@/utils/loginReturnTo';

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
// @ts-ignore -- The existing SVG loader type is not declared by the app.
import Wxpro from "./icons/wxpro.svg?react";

interface LoginBridgeProps {
    oauthData: any;
    onHasLdap: (v: boolean) => void;
    kunlianTarget?: string;
}

export default function LoginBridge({ oauthData, onHasLdap, kunlianTarget }: LoginBridgeProps) {
    const { t } = useTranslation();

    const ssoUrl = oauthData?.sso || "";
    const wxUrl = oauthData?.wx || "";
    const hasKunlian = oauthData?.kunlian === '/api/oauth2/kunlian';

    useEffect(() => {
        if (oauthData?.ldap) onHasLdap(true);
    }, [oauthData]);

    if (!ssoUrl && !wxUrl && !hasKunlian) return null;

    return (
        <div>
            <Separator className="my-4" text={t("login.otherMethods")}></Separator>
            <div className="flex justify-center items-center gap-4">
                {hasKunlian && <Button size="small" color="default" variant="outlined" onClick={() => {
                    const entry = parseKunlianWorkflowEntry(kunlianTarget ?? '');
                    if (entry.kind === 'invalid-entry') return;
                    if (entry.kind === 'edit' && !claimKunlianWorkflowLoginAttempt(entry, { manual: true })) return;
                    location.href = buildKunlianLoginUrl(kunlianTarget);
                }}>
                    {t('shared:kunlian.login')}
                </Button>}
                {ssoUrl && (
                    <Button size="small" iconOnly onClick={() => (location.href = ssoUrl)}>
                        SSO
                    </Button>
                )}
                {wxUrl && (
                    <Button size="small" iconOnly variant="text" onClick={() => (location.href = wxUrl)} color="default">
                        <Wxpro />
                    </Button>
                )}
            </div>
        </div>
    );
}
