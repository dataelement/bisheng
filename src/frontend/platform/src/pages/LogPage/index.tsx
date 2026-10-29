import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { userContext } from "@/contexts/userContext";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import AbnormalFilesTab from "./abnormalUpload/AbnormalFilesTab";
import { canSeeAbnormalFiles } from "./abnormalUpload/access";
import SystemLog from "./systemLog";
import AppUseLog from "./useAppLog";

export default function index() {
    const { t } = useTranslation()
    const { user } = useContext(userContext)
    const [searchParams] = useSearchParams()
    const showAbnormalFiles = canSeeAbnormalFiles(user)
    const [tab, setTab] = useState("app")

    useEffect(() => {
        if (searchParams.get("tab") === "files" && showAbnormalFiles) {
            setTab("files")
        }
    }, [searchParams, showAbnormalFiles])

    return <div id="model-scroll" className="w-full h-full px-2 pt-4">
        <Tabs value={tab} className="w-full mb-[40px]" onValueChange={setTab}>
            <TabsList className="">
                <TabsTrigger value="app">{t('log.appUsage')}</TabsTrigger>
                <TabsTrigger value="system">{t('log.systemOperations')}</TabsTrigger>
                {showAbnormalFiles && <TabsTrigger value="files">{t('log.abnormalFiles')}</TabsTrigger>}
            </TabsList>
            <TabsContent value="app">
                <AppUseLog />
            </TabsContent>
            <TabsContent value="system">
                <SystemLog />
            </TabsContent>
            {showAbnormalFiles && <TabsContent value="files">
                <AbnormalFilesTab />
            </TabsContent>}
        </Tabs>
    </div>
};
