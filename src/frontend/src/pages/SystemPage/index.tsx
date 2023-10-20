
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/ui/tabs";
import Roles from "./components/Roles";
import Config from "./components/Config";
import Users from "./components/Users";

export default function FileLibPage() {

    return <div className="w-full h-screen p-6 overflow-y-auto">
        <Tabs defaultValue="account" className="w-full">
            <TabsList className="">
                <TabsTrigger value="account" className="roundedrounded-xl">用户管理</TabsTrigger>
                <TabsTrigger value="role">角色管理</TabsTrigger>
                <TabsTrigger value="password">系统配置</TabsTrigger>
            </TabsList>
            <TabsContent value="account">
                <Users></Users>
            </TabsContent>
            <TabsContent value="role">
                <Roles></Roles>
            </TabsContent>
            <TabsContent value="password">
                <Config></Config>
            </TabsContent>
        </Tabs>
    </div>
};
