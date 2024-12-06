import Separator from "@/components/bs-comp/chatComponent/Separator";
import { Button } from "@/components/bs-ui/button";
import { getSSOurlApi } from "@/controllers/API/pro";
import { useEffect, useState } from "react";
//@ts-ignore
import Wxpro from "./icons/wxpro.svg?react";
import { useTranslation } from "react-i18next";

export default function LoginBridge({ onHasLdap }) {

    const { t } = useTranslation()

    const [ssoUrl, setSsoUrl] = useState<string>('')
    const [wxUrl, setWxUrl] = useState<string>('')

    useEffect(() => {
        getSSOurlApi().then((urls: any) => {
            setSsoUrl(urls.sso)
            setWxUrl(urls.wx)
            urls.ldap && onHasLdap(true)
        })
    }, [])

    if (!ssoUrl && !wxUrl) return null

    return <div>
        <Separator className="my-4" text={t('login.otherMethods')}></Separator>
        <div className="flex justify-center items-center gap-4">
            {ssoUrl && <Button size="icon" className="rounded-full" onClick={() => location.href = ssoUrl}>SSO</Button>}
            {wxUrl && <Button size="icon" variant="ghost" onClick={() => location.href = wxUrl}><Wxpro /></Button>}
        </div>
    </div>
};
