import { Button } from "@/components/bs-ui/button";
import { ReactComponent as Wxpro } from "./icons/wxpro.svg";
import Separator from "@/components/bs-comp/chatComponent/Separator";

export default function LoginBridge() {

    const clickQwLogin = () => {
        location.href = window.WX_LOGIN_URL
    }

    return <div>
        <Separator className="my-4" text="其他登录方式"></Separator>
        <div className="flex justify-center items-center gap-4">
            <Button size="icon" variant="ghost" onClick={clickQwLogin}><Wxpro /></Button>
        </div>
    </div>
};
