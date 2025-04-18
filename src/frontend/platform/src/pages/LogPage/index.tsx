import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { useTranslation } from "react-i18next";
import SystemLog from "./systemLog";
import AppUseLog from "./useAppLog";

export default function index() {
    const { t } = useTranslation()

    return <div id="model-scroll" className="w-full h-full px-2 pt-4">
        <Tabs defaultValue="app" className="w-full mb-[40px]" onValueChange={e => { }}>
            <TabsList className="">
                <TabsTrigger value="app">{t('log.appUsage')}</TabsTrigger>
                <TabsTrigger value="system">{t('log.systemOperations')}</TabsTrigger>
            </TabsList>
            <TabsContent value="app">
                <AppUseLog />
            </TabsContent>
            <TabsContent value="system">
                <SystemLog />
            </TabsContent>
        </Tabs>
    </div>
};
