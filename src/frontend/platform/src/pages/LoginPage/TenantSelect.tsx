// @ts-strict-ignore
import { Button } from '@bisheng/ui';

import { logoutApi } from "@/controllers/API/user";
import { showApiError } from "@/controllers/request";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

export default function TenantSelect() {
    const { t } = useTranslation("bs");

    useEffect(() => {
        sessionStorage.removeItem("pending_tenants");
        if (localStorage.getItem("isLogin") !== "1") return;

        const timer = window.setTimeout(() => {
            location.href = `${__APP_ENV__.BASE_URL}/admin`;
        }, 1200);

        return () => window.clearTimeout(timer);
    }, []);

    const handleContinue = () => {
        location.href = `${__APP_ENV__.BASE_URL}/admin`;
    };

    const handleBackToLogin = () => {
        sessionStorage.removeItem("pending_tenants");
        logoutApi().then(() => {
                // @ts-ignore
                location.href = __APP_ENV__.BASE_URL || "/";
            }).catch(showApiError);
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-background">
            <div className="w-full max-w-md px-6">
                <h1 className="text-2xl font-bold text-center mb-8">{t("tenant.selectionDeprecatedTitle")}</h1>
                <div className="rounded-lg border bg-card p-6 text-center shadow-sm">
                    <p className="text-sm leading-6 text-muted-foreground">{t("tenant.selectionDeprecatedDesc")}</p>
                    <p className="mt-3 text-sm leading-6 text-muted-foreground">
                        {t("tenant.selectionDeprecatedRedirect")}
                    </p>
                    <div className="mt-6 flex justify-center gap-3">
                        <Button onClick={handleContinue}>{t("tenant.continueToAdmin")}</Button>
                        <Button variant="outlined" onClick={handleBackToLogin} color="default">
                            {t("tenant.backToLogin")}
                        </Button>
                    </div>
                </div>
            </div>
        </div>
    );
}
