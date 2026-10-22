import { Button } from '@bisheng/ui';
import Separator from "@/components/bs-comp/chatComponent/Separator";

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
// @ts-ignore -- The existing SVG loader type is not declared by the app.
import Wxpro from "./icons/wxpro.svg?react";

interface LoginBridgeProps {
    oauthData: any;
    onHasLdap: (v: boolean) => void;
}

export default function LoginBridge({ oauthData, onHasLdap }: LoginBridgeProps) {
    const { t } = useTranslation();

    const ssoUrl = oauthData?.sso || "";
    const wxUrl = oauthData?.wx || "";

    useEffect(() => {
        if (oauthData?.ldap) onHasLdap(true);
    }, [oauthData]);

    if (!ssoUrl && !wxUrl) return null;

    return (
        <div>
            <Separator className="my-4" text={t("login.otherMethods")}></Separator>
            <div className="flex justify-center items-center gap-4">
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
