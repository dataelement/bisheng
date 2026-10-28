import { useContext } from "react";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { RuntimeAuditPanel } from "./runtime/RuntimeAuditPanel";
import { Tabs } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import SystemLog from "./systemLog";
import AppUseLog from "./useAppLog";

export function LogPage() {
    const { t } = useTranslation()
    const { appConfig } = useContext(locationContext)
    const { user } = useContext(userContext)
    const showRuntime = !!appConfig.appRuntimeEnabled && (user?.role === "admin" || !!user?.is_child_admin)

    return <div id="model-scroll" className="w-full h-full px-2 pt-4">
        <Tabs defaultActiveKey="app" className="w-full mb-10 [&>div:first-child]:mx-2" items={[
            { key: 'app', label: t('log.appUsage'), children: <div className="pt-2"><AppUseLog /></div> },
            { key: 'system', label: t('log.systemOperations'), children: <div className="pt-2"><SystemLog /></div> },
            ...(showRuntime ? [{ key: "runtime", label: t("log.runtime.title"), children: <RuntimeAuditPanel /> }] : []),
        ]} />
    </div>
};
