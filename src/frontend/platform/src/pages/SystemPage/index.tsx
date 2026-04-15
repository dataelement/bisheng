import { userContext } from "@/contexts/userContext"
import { useContext } from "react"
import { useTranslation } from "react-i18next"
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../../components/bs-ui/tabs"
import Config from "./components/Config"
import OrganizationAndMembers from "./components/OrganizationAndMembers"
import RolesAndPermissions from "./components/RolesAndPermissions"
import Theme from "./theme"
import UserGroups from "./components/UserGroup"
import Users from "./components/Users"

export default function index() {
  const { user } = useContext(userContext)

  const { t } = useTranslation()
  const defaultTab =
    user.role === "admin" ? "organization" : "user"

  return (
    <div className="h-full w-full px-2 pt-4">
      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="">
          {user.role === "admin" && (
            <TabsTrigger value="organization">
              {t("system.orgAndMembers")}
            </TabsTrigger>
          )}
          {user.role !== "admin" && (
            <TabsTrigger value="user" className="roundedrounded-xl">
              {t("system.userManagement")}
            </TabsTrigger>
          )}
          {user.role === "admin" && (
            <TabsTrigger value="userGroup">{t("system.userGroupsM")}</TabsTrigger>
          )}
          <TabsTrigger value="role">{t("system.roleManagement")}</TabsTrigger>
          {user.role === "admin" && (
            <TabsTrigger value="system">{t("system.systemConfiguration")}</TabsTrigger>
          )}
          {user.role === "admin" && (
            <TabsTrigger value="theme">{t("system.themeColor")}</TabsTrigger>
          )}
        </TabsList>
        {user.role === "admin" && (
          <TabsContent value="organization">
            <OrganizationAndMembers />
          </TabsContent>
        )}
        {user.role !== "admin" && (
          <TabsContent value="user">
            <Users />
          </TabsContent>
        )}
        {user.role === "admin" && (
          <TabsContent value="userGroup">
            <UserGroups />
          </TabsContent>
        )}
        <TabsContent value="role">
          <RolesAndPermissions />
        </TabsContent>
        {user.role === "admin" && (
          <TabsContent value="system">
            <Config />
          </TabsContent>
        )}
        {user.role === "admin" && (
          <TabsContent value="theme">
            <Theme />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
