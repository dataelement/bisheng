import { userContext } from "@/contexts/userContext";
import { useContext } from "react";
import { useTranslation } from "react-i18next";
import {
    Tabs,
    TabsContent,
    TabsList,
    TabsTrigger,
} from "../../components/bs-ui/tabs";
import Config from "./components/Config";
import Roles from "./components/Roles";
import Theme from "./theme";
import UserGroups from "./components/UserGroup";
import Users from "./components/Users";

export default function index() {
    const { user } = useContext(userContext);

    const { t } = useTranslation()
    return <div className="w-full h-full px-2 pt-4">

        <Tabs defaultValue="user" className="w-full">
            <TabsList className="">
                <TabsTrigger value="user" className="roundedrounded-xl">{t('system.userManagement')}</TabsTrigger>
                {user.role === 'admin' && <TabsTrigger value="userGroup">{t('system.userGroupsM')}</TabsTrigger>}
                <TabsTrigger value="role">{t('system.roleManagement')}</TabsTrigger>
                {user.role === 'admin' && <TabsTrigger value="system">{t('system.systemConfiguration')}</TabsTrigger>}
                {user.role === 'admin' && <TabsTrigger value="theme">{t('system.themeColor')}</TabsTrigger>}
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
            <TabsContent value="theme">
                <Theme></Theme>
            </TabsContent>
        </Tabs>
    </div>
};
