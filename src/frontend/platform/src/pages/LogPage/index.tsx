import { useContext } from "react";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { RuntimeAuditPanel } from "./runtime/RuntimeAuditPanel";
import { Tabs } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import { useTranslation } from "react-i18next";
import SystemLog from "./systemLog";
import AppUseLog from "./useAppLog";
import { AuditScopeNotice } from "./components/AuditScopeNotice";

export function LogPage() {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    const { user } = useContext(userContext)
    const showRuntime = !!appConfig.appRuntimeEnabled && (user?.role === "admin" || !!user?.is_child_admin)

    return <div id="model-scroll" className="flex min-h-0 w-full h-full flex-col px-2 pt-4 overflow-hidden">
        <AuditScopeNotice />
        <Tabs defaultActiveKey="app" className="flex min-h-0 flex-1 flex-col w-full [&>div:first-child]:mx-2 [&>div:first-child]:shrink-0 [&>[role=tabpanel][data-state=active]]:flex [&>[role=tabpanel][data-state=active]]:min-h-0 [&>[role=tabpanel][data-state=active]]:flex-1 [&>[role=tabpanel][data-state=active]]:flex-col [&>[role=tabpanel][data-state=active]]:overflow-hidden" items={[
            { key: 'app', label: t('log.appUsage'), icon: <Outlined.Application aria-hidden="true" />, children: <div className="flex min-h-0 flex-1 flex-col pt-2"><AppUseLog /></div> },
            { key: 'system', label: t('log.systemOperations'), icon: <Outlined.History aria-hidden="true" />, children: <div className="flex min-h-0 flex-1 flex-col pt-2"><SystemLog /></div> },
            ...(showRuntime ? [{ key: "runtime", label: t("log.runtime.title"), icon: <Outlined.DeviceDesktopExchange aria-hidden="true" />, children: <RuntimeAuditPanel /> }] : []),
        ]} />
    </div>
};
