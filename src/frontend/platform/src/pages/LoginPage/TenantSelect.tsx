import { Button } from "@/components/bs-ui/button";
import { logoutApi } from "@/controllers/API/user";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
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
    captureAndAlertRequestErrorHoc(
      logoutApi().then(() => {
        // @ts-ignore
        location.href = __APP_ENV__.BASE_URL || "/";
      })
    );
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="w-full max-w-md px-6">
        <h1 className="text-2xl font-bold text-center mb-8">
          {t("tenant.selectionDeprecatedTitle", { defaultValue: "租户选择已下线" })}
        </h1>
        <div className="rounded-lg border bg-card p-6 text-center shadow-sm">
          <p className="text-sm leading-6 text-muted-foreground">
            {t("tenant.selectionDeprecatedDesc", {
              defaultValue:
                "v2.5.1 起，租户不再由用户手动切换，系统会按主部门自动派生当前租户。",
            })}
          </p>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {t("tenant.selectionDeprecatedRedirect", {
              defaultValue: "如果你已登录，页面会自动跳转到管理端。",
            })}
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <Button onClick={handleContinue}>
              {t("tenant.continueToAdmin", { defaultValue: "继续进入管理端" })}
            </Button>
            <Button variant="outline" onClick={handleBackToLogin}>
              {t("tenant.backToLogin")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
