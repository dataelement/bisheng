import { useContext, useState } from "react";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { RuntimeAuditPanel } from "./runtime/RuntimeAuditPanel";
import { Segmented, Tabs } from "@bisheng/ui";
import type { RuntimeAuditKind } from "@/controllers/API/runtimeAudit";
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
    const [selectedTab, setSelectedTab] = useState("app")
    const [runtimeKind, setRuntimeKind] = useState<RuntimeAuditKind>("model")
    const activeTab = !showRuntime && selectedTab === "runtime" ? "app" : selectedTab

    const handleTabChange = (key: string) => {
        setSelectedTab(key)
        if (key === "runtime") setRuntimeKind("model")
    }

    return <div id="model-scroll" className="flex min-h-0 w-full h-full flex-col px-2 pt-4 has-[>.audit-scope-notice]:pt-2 overflow-hidden">
        <AuditScopeNotice />
        <Tabs
            activeKey={activeTab}
            onChange={handleTabChange}
            className="flex min-h-0 flex-1 flex-col w-full [&>div:first-child]:mx-2 [&>div:first-child]:shrink-0 [&>div:first-child]:flex-wrap [&>div:first-child]:gap-x-6 [&>div:first-child]:gap-y-2 [&>div:first-child>div:nth-child(2)]:ml-0 [&>div:first-child>div:nth-child(2)]:max-w-full [&>div:first-child>div:nth-child(2)]:pl-0 [&>[role=tabpanel][data-state=active]]:flex [&>[role=tabpanel][data-state=active]]:min-h-0 [&>[role=tabpanel][data-state=active]]:flex-1 [&>[role=tabpanel][data-state=active]]:flex-col [&>[role=tabpanel][data-state=active]]:overflow-hidden"
            extra={activeTab === "runtime" ? (
                <div className="min-w-0 max-w-full overflow-x-auto">
                    <Segmented
                        aria-label={t('log.runtime.title')}
                        value={runtimeKind}
                        onChange={value => setRuntimeKind(value as RuntimeAuditKind)}
                        options={(['model', 'capability', 'access'] as const).map(value => ({ value, label: t(`log.runtime.${value}Tab`) }))}
                    />
                </div>
            ) : undefined}
            items={[
                { key: 'app', label: t('log.appUsage'), icon: <Outlined.Application aria-hidden="true" />, children: <div className="flex min-h-0 flex-1 flex-col pt-2"><AppUseLog /></div> },
                { key: 'system', label: t('log.systemOperations'), icon: <Outlined.History aria-hidden="true" />, children: <div className="flex min-h-0 flex-1 flex-col pt-2"><SystemLog /></div> },
                ...(showRuntime ? [{ key: "runtime", label: t("log.runtime.title"), icon: <Outlined.DeviceDesktopExchange aria-hidden="true" />, children: <RuntimeAuditPanel kind={runtimeKind} /> }] : []),
            ]}
        />
    </div>
};
