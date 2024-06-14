import Separator from "@/components/bs-comp/chatComponent/Separator";
import { Button } from "@/components/bs-ui/button";
import { getSSOurlApi } from "@/controllers/API/pro";
import { useEffect, useRef } from "react";
import { ReactComponent as Wxpro } from "./icons/wxpro.svg";

export default function LoginBridge() {



    const urlRef = useRef<string>('')
    useEffect(() => {
        getSSOurlApi().then(url => urlRef.current = url)
    }, [])

    const clickQwLogin = () => {
        location.href = urlRef.current
    }

    return <div>
        <Separator className="my-4" text="其他登录方式"></Separator>
        <div className="flex justify-center items-center gap-4">
            <Button size="icon" variant="ghost" onClick={clickQwLogin}><Wxpro /></Button>
        </div>
    </div>
};
