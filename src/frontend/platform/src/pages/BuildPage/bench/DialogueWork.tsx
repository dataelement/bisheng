// DialogueWork.tsx
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { ScopeBar } from "@/pages/ModelPage/manage/ScopeBar";
import { Tabs } from "@bisheng/ui";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AppCenter } from "./AppCenter";
import Index from "./index";
import KnowledgeSpace from "./KnowledgeSpace";
import Subscribe from "./Subscribe";

export default function DialogueWork() {
    const [activeTab, setActiveTab] = useState("client");
    const [scopeVersion, setScopeVersion] = useState(0);
    const { t, i18n } = useTranslation();
    const { user } = useContext(userContext);
    const { appConfig } = useContext(locationContext);
    useEffect(() => {
        i18n.loadNamespaces("tool");
    }, [i18n]);

    return (
        <div className="w-full h-full px-2 pt-4 relative">
            <div className="mb-4 flex items-center gap-3">
                {appConfig.multiTenantEnabled && <ScopeBar user={user} onScopeChange={() => setScopeVersion((value) => value + 1)} />}
                <Tabs
                    activeKey={activeTab}
                    onChange={setActiveTab}
                    aria-label={t("build.workbench")}
                    items={[
                        { key: "client", label: t("bench.home") },
                        { key: "knowledgeSpace", label: t("bench.knowledgeSpace") },
                        { key: "subscribe", label: t("bench.subscribe") },
                        { key: "appCenter", label: t("bench.appCenter") },
                    ]}
                />
            </div>
            {activeTab === "client" && <Index scopeVersion={scopeVersion} />}
            {activeTab === "knowledgeSpace" && <KnowledgeSpace scopeVersion={scopeVersion} />}
            {activeTab === "subscribe" && <Subscribe scopeVersion={scopeVersion} />}
            {activeTab === "appCenter" && <AppCenter scopeVersion={scopeVersion} />}
        </div>
    );
}
