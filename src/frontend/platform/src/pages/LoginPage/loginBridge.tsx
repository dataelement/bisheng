import Separator from "@/components/bs-comp/chatComponent/Separator";
import { Button } from "@/components/bs-ui/button";
import { useEffect } from "react";
//@ts-ignore
import Wxpro from "./icons/wxpro.svg?react";
import { useTranslation } from "react-i18next";

interface LoginBridgeProps {
    oauthData: any;
    onHasLdap: (v: boolean) => void;
}

export default function LoginBridge({ oauthData, onHasLdap }: LoginBridgeProps) {

    const { t } = useTranslation()

    const ssoUrl = oauthData?.sso || ''
    const wxUrl = oauthData?.wx || ''

    useEffect(() => {
        if (oauthData?.ldap) onHasLdap(true)
    }, [oauthData])

    if (!ssoUrl && !wxUrl) return null

    return <div>
        <Separator className="my-4" text={t('login.otherMethods')}></Separator>
        <div className="flex justify-center items-center gap-4">
            {ssoUrl && <Button size="icon" className="rounded-full" onClick={() => location.href = ssoUrl}>SSO</Button>}
            {wxUrl && <Button size="icon" variant="ghost" onClick={() => location.href = wxUrl}><Wxpro /></Button>}
        </div>
    </div>
};
