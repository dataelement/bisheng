import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { userContext } from "@/contexts/userContext";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useSearchParams } from "react-router-dom";
import { isStandalonePath } from "@/routes/standalone";
import AbnormalFilesTab from "./abnormalUpload/AbnormalFilesTab";
import { canSeeAbnormalFiles } from "./abnormalUpload/access";
import SystemLog from "./systemLog";
import AppUseLog from "./useAppLog";

export default function index() {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const { pathname } = useLocation()
    const [searchParams] = useSearchParams()
    const showAbnormalFiles = canSeeAbnormalFiles(user)
    const [tab, setTab] = useState("app")
    const paneHeight = isStandalonePath(pathname) ? "h-full" : "h-[calc(100vh-64px)]"

    useEffect(() => {
        if (searchParams.get("tab") === "files" && showAbnormalFiles) {
            setTab("files")
        }
    }, [searchParams, showAbnormalFiles])

    return <div id="model-scroll" className={`flex w-full min-h-0 min-w-0 flex-col overflow-hidden px-2 pt-4 ${paneHeight}`}>
        <Tabs value={tab} className="flex min-h-0 min-w-0 w-full flex-1 flex-col" onValueChange={setTab}>
            <TabsList className="shrink-0 self-start">
                <TabsTrigger value="app">{t('log.appUsage')}</TabsTrigger>
                <TabsTrigger value="system">{t('log.systemOperations')}</TabsTrigger>
                {showAbnormalFiles && <TabsTrigger value="files">{t('log.abnormalFiles')}</TabsTrigger>}
            </TabsList>
            <TabsContent value="app" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                <AppUseLog />
            </TabsContent>
            <TabsContent value="system" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                <SystemLog />
            </TabsContent>
            {showAbnormalFiles && <TabsContent value="files" className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
                <AbnormalFilesTab />
            </TabsContent>}
        </Tabs>
    </div>
};
