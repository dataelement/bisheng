import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs";
import { t } from "i18next";
import SystemLog from "./systemLog";
import AppUseLog from "./useAppLog";

export default function index() {


    return <div id="model-scroll" className="w-full h-full px-2 pt-4">
        <Tabs defaultValue="app" className="w-full mb-[40px]" onValueChange={e => { }}>
            <TabsList className="">
                <TabsTrigger value="app">应用使用</TabsTrigger>
                <TabsTrigger value="system">系统操作</TabsTrigger>
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
