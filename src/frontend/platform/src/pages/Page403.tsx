// @ts-strict-ignore
import { Button } from '@bisheng/ui';

import { logoutApi } from "@/controllers/API/user";
import { useState } from "react";
import { useTranslation } from "react-i18next";

export default function Page403() {
    const { t } = useTranslation("bs");
    const [loggingOut, setLoggingOut] = useState(false);

    const clearLocalSession = () => {
        localStorage.removeItem("isLogin");
        localStorage.removeItem("ws_token");
        localStorage.removeItem("UUR_INFO");
        localStorage.removeItem("LOGIN_PATHNAME");
    };

    const handleLogout = async () => {
        if (loggingOut) return;
        setLoggingOut(true);

        const thirdPartyLogoutUrl = localStorage.getItem("THIRD_PARTY_LOGOUT_URL");

        try {
            await logoutApi();
        } catch {
            // Clear local credentials even when the remote logout fails.
        } finally {
            clearLocalSession();
            window.location.href = thirdPartyLogoutUrl || __APP_ENV__.BASE_URL + "/";
        }
    };

    return (
        <div className="fixed left-0 top-0 z-50 flex h-full w-full items-center justify-center bg-black bg-opacity-70">
            <div className="flex w-[90%] max-w-lg text-center min-h-[200px] flex-col justify-center rounded-lg p-8 shadow-xl bg-gray-50">
                <h1 className="mb-4 text-4xl font-bold text-red-600">403</h1>
                <p className="mb-8 text-lg text-gray-800">{t("publicPages.forbidden")}</p>
                <div className="flex justify-center">
                    <Button type="button" variant="solid" disabled={loggingOut} onClick={handleLogout} color="primary">
                        {loggingOut ? t("publicPages.loggingOut") : t("publicPages.switchAccount")}
                    </Button>
                </div>
            </div>
        </div>
    );
}
