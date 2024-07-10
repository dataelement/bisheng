import Separator from "@/components/bs-comp/chatComponent/Separator";
import { Button } from "@/components/bs-ui/button";
import { getSSOurlApi } from "@/controllers/API/pro";
import { useEffect, useRef } from "react";
//@ts-ignore
import { ReactComponent as Wxpro } from "./icons/wxpro.svg";
import { useTranslation } from "react-i18next";

export default function LoginBridge({onHasLdap}) {

    const { t } = useTranslation()

    const urlRef = useRef<string>('')
    useEffect(() => {
        getSSOurlApi().then((urls:any) => {
            urlRef.current = urls.wx
            urls.ldap && onHasLdap(true)
        })
    }, [])

    const clickQwLogin = () => {
        location.href = urlRef.current
    }

    return <div>
        <Separator className="my-4" text={t('login.otherMethods')}></Separator>
        <div className="flex justify-center items-center gap-4">
            <Button size="icon" variant="ghost" onClick={clickQwLogin}><Wxpro /></Button>
        </div>
    </div>
};
