import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/ui/tabs";
import Roles from "./components/Roles";
import Config from "./components/Config";
import Users from "./components/Users";
import { useTranslation } from "react-i18next";
import UserGroups from "./components/UserGroup";
import { userContext } from "@/contexts/userContext";
import { useContext } from "react";

export default function FileLibPage() {
    const { user } = useContext(userContext);

    const { t } = useTranslation()
    return <div className="w-full h-full px-2 py-4">

        <Tabs defaultValue="user" className="w-full">
            <TabsList className="">
                <TabsTrigger value="user" className="roundedrounded-xl">{t('system.userManagement')}</TabsTrigger>
                {user.role === 'admin' && <TabsTrigger value="userGroup">{t('system.userGroupsM')}</TabsTrigger>}
                <TabsTrigger value="role">{t('system.roleManagement')}</TabsTrigger>
                {user.role === 'admin' && <TabsTrigger value="system">{t('system.systemConfiguration')}</TabsTrigger>}
            </TabsList>
            <TabsContent value="user">

                <Users></Users>
            </TabsContent>
            <TabsContent value="userGroup">
                <UserGroups></UserGroups>
            </TabsContent>
            <TabsContent value="role">
                <Roles></Roles>
            </TabsContent>
            <TabsContent value="system">
                <Config></Config>
            </TabsContent>
        </Tabs>
    </div>
};
