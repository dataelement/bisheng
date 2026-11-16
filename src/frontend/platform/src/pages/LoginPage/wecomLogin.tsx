import { Button } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
// @ts-expect-error -- the SVG loader type is not declared by the app.
import Wxpro from "./icons/wxpro.svg?react";
import Separator from "@/components/bs-comp/chatComponent/Separator";

interface WeComLoginProps {
    /** Backend path that starts the authorization (from the availability API). */
    loginPath: string;
    /** `silent` inside the WeCom app browser, `qr` on a desktop browser. */
    mode: string | null;
}

/**
 * F120 self-hosted WeCom sign-in entry.
 *
 * Unlike the gateway buttons in `loginBridge.tsx` this one renders without the
 * commercial edition: it is shown whenever the backend reports an enabled WeCom
 * org-sync configuration and no gateway.
 */
export function WeComLogin({ loginPath, mode }: WeComLoginProps) {
    const { t } = useTranslation();

    const handleClick = () => {
        const base = (import.meta.env.BASE_URL || "/").replace(/\/$/, "");
        const params = new URLSearchParams({ return_to: window.location.href });
        if (mode) params.set("mode", mode);
        window.location.href = `${base}${loginPath}?${params.toString()}`;
    };

    return (
        <div>
            <Separator className="my-4" text={t("login.otherMethods")} />
            <div className="flex justify-center items-center gap-4">
                <Button size="small" variant="text" color="default" onClick={handleClick}>
                    <span className="flex items-center gap-2">
                        <Wxpro />
                        {t("login.wecomLogin")}
                    </span>
                </Button>
            </div>
        </div>
    );
}
