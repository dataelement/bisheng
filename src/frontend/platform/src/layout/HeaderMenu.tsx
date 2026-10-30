import { Segmented } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { userContext } from "@/contexts/userContext";
import { canManageWorkbenchConfig } from "@/pages/ModelPage/manage/permissions";
import { useContext, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router-dom";

export function HeaderMenu() {
    const { t } = useTranslation();
    const location = useLocation();
    const navigate = useNavigate();

    const { user } = useContext(userContext);
    // Resolve navigation from the current administrative identity.
    const isAdmin = useMemo(() => {
        return user.role === "admin";
    }, [user]);
    const canOpenBuild =
        isAdmin ||
        Boolean(user.is_child_admin) ||
        Boolean(user.web_menu?.includes("build")) ||
        Boolean(user.web_menu?.includes("create_app"));
    const canManageWorkbench = canManageWorkbenchConfig(user);

    if (
        ["/build/apps", "/build/tools", "/build/client"].includes(location.pathname.replace(__APP_ENV__.BASE_URL, ""))
    ) {
        return (
            <div className="build-tab flex justify-center h-[65px] items-center relative">
                <Segmented
                    size="large"
                    className="rounded-full [&>span[aria-hidden]]:rounded-full"
                    aria-label={t("menu.skills")}
                    value={location.pathname.replace(__APP_ENV__.BASE_URL, "").split("/").pop()}
                    onChange={(value) => navigate(`/build/${value}`)}
                    options={[
                        ...(canOpenBuild ? [
                            { value: "apps", label: t("build.app"), icon: <Outlined.Application aria-hidden="true" /> },
                            { value: "tools", label: t("build.tools"), icon: <Outlined.Hammer aria-hidden="true" /> },
                        ] : []),
                        ...(canManageWorkbench ? [{ value: "client", label: t("build.workbench"), icon: <Outlined.DeviceDesktopExchange aria-hidden="true" /> }] : []),
                    ]}
                />
            </div>
        );
    }

    if (["/model/management", "/model/finetune"].includes(location.pathname.replace(__APP_ENV__.BASE_URL, ""))) {
        return (
            <div className="build-tab flex justify-center h-[65px] items-center relative">
                <Segmented
                    size="large"
                    className="rounded-full [&>span[aria-hidden]]:rounded-full"
                    aria-label={t("model.modelManagement")}
                    value={location.pathname.replace(__APP_ENV__.BASE_URL, "").split("/").pop()}
                    onChange={(value) => navigate(`/model/${value}`)}
                    options={[
                        { value: "management", label: t("model.modelManagement"), icon: <Outlined.BlocksAndArrows aria-hidden="true" /> },
                        { value: "finetune", label: t("model.modelFineTune"), icon: <Outlined.Setting aria-hidden="true" /> },
                    ]}
                />
            </div>
        );
    }

    if (location.pathname.replace(__APP_ENV__.BASE_URL, "") === "/approval") {
        return <div id="approval-header-menu" className="flex h-[65px] items-center justify-center" />;
    }

    return null;
}
