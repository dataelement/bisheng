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
  const isSuperAdmin = user?.role === "admin"
  const isDeptAdmin = !!user?.is_department_admin
  const showOrgTab = isSuperAdmin || isDeptAdmin
  const canAccessSystemConfig = isSuperAdmin || isDeptAdmin
  const showUserGroupTab =
    user?.role === "admin" || !!user?.can_manage_user_groups
  /** 仅非部门管理员、非超管展示旧版扁平用户表（依赖用户组维度） */
  const showLegacyUserTab = !isSuperAdmin && !isDeptAdmin

  const defaultTab = showOrgTab
    ? "organization"
    : showUserGroupTab
      ? "userGroup"
      : "user"

  return (
    <div className="h-full w-full px-2 pt-4">
      <Tabs defaultValue={defaultTab} className="w-full">
        <TabsList className="">
          {showOrgTab && (
            <TabsTrigger value="organization">
              {t("system.orgAndMembers")}
            </TabsTrigger>
          )}
          {showLegacyUserTab && (
            <TabsTrigger value="user" className="roundedrounded-xl">
              {t("system.userManagement")}
            </TabsTrigger>
          )}
          {showUserGroupTab && (
            <TabsTrigger value="userGroup">{t("system.userGroupsM")}</TabsTrigger>
          )}
          <TabsTrigger value="role">{t("system.roleAndPermissions")}</TabsTrigger>
          {canAccessSystemConfig && (
            <TabsTrigger value="system">{t("system.systemConfiguration")}</TabsTrigger>
          )}
          {canAccessSystemConfig && (
            <TabsTrigger value="theme">{t("system.themeColor")}</TabsTrigger>
          )}
        </TabsList>
        {showOrgTab && (
          <TabsContent value="organization">
            <OrganizationAndMembers />
          </TabsContent>
        )}
        {showLegacyUserTab && (
          <TabsContent value="user">
            <Users />
          </TabsContent>
        )}
        {showUserGroupTab && (
          <TabsContent value="userGroup">
            <UserGroups />
          </TabsContent>
        )}
        <TabsContent value="role">
          <RolesAndPermissions />
        </TabsContent>
        {canAccessSystemConfig && (
          <TabsContent value="system">
            <Config />
          </TabsContent>
        )}
        {canAccessSystemConfig && (
          <TabsContent value="theme">
            <Theme />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
