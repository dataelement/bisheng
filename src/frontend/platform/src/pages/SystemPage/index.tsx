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
import OrgSync from "./components/OrgSync"
import RolesAndPermissions from "./components/RolesAndPermissions"
import Theme from "./theme"
import UserGroups from "./components/UserGroup"
import Users from "./components/Users"

export default function index() {
  const { user } = useContext(userContext)

  const { t } = useTranslation()
  const isSuperAdmin = user?.role === "admin"
  const isDeptAdmin = !!user?.is_department_admin
  const isChildAdmin = !!user?.is_child_admin
  /** PRD §3.3: org tab is per-Tenant. Super admin sees full tree;
   *  Child Admin manages own Child; dept admin manages own subtree. */
  const showOrgTab = isSuperAdmin || isDeptAdmin || isChildAdmin
  /** PRD §3.3 / §5.5: role mgmt scoped to admins (super / Child / dept). */
  const showRoleTab = isSuperAdmin || isDeptAdmin || isChildAdmin
  /** System config edits instance-level config.yaml; theme writes
   *  instance-level CSS vars/logo. Neither has per-Tenant semantics,
   *  so restrict to global super admin only. */
  const canAccessSystemConfig = isSuperAdmin
  /** 组织同步仅超级管理员可见（网关掉对接口推送后，本页只读看记录与日志） */
  const showOrgSyncTab = isSuperAdmin
  /** PRD §4.5: Child Admin manages own tenant's user groups. Backend now
   *  flips can_manage_user_groups true for Child Admin too; the explicit
   *  is_child_admin term keeps the tab visible if the backend regresses. */
  const showUserGroupTab =
    user?.role === "admin"
    || !!user?.can_manage_user_groups
    || !!user?.is_child_admin
  /** Legacy flat user table is for accounts without org-tab access. */
  const showLegacyUserTab = !showOrgTab

  const defaultTab = showOrgTab
    ? "organization"
    : showUserGroupTab
      ? "userGroup"
      : "user"

  return (
    <div className="flex h-full w-full flex-col px-2 pt-4">
      <Tabs defaultValue={defaultTab} className="flex min-h-0 w-full flex-1 flex-col">
        <TabsList className="shrink-0 self-start">
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
          {showRoleTab && (
            <TabsTrigger value="role">{t("system.roleAndPermissions")}</TabsTrigger>
          )}
          {showOrgSyncTab && (
            <TabsTrigger value="orgSync">{t("orgSync:title", "组织同步")}</TabsTrigger>
          )}
          {canAccessSystemConfig && (
            <TabsTrigger value="system">{t("system.systemConfiguration")}</TabsTrigger>
          )}
          {canAccessSystemConfig && (
            <TabsTrigger value="theme">{t("system.themeColor")}</TabsTrigger>
          )}
        </TabsList>
        {showOrgTab && (
          <TabsContent value="organization" className="min-h-0 flex-1 overflow-hidden">
            <OrganizationAndMembers />
          </TabsContent>
        )}
        {showLegacyUserTab && (
          <TabsContent value="user" className="min-h-0 flex-1 overflow-hidden">
            <Users />
          </TabsContent>
        )}
        {showUserGroupTab && (
          <TabsContent value="userGroup" className="min-h-0 flex-1 overflow-hidden">
            <UserGroups />
          </TabsContent>
        )}
        {showRoleTab && (
          <TabsContent value="role" className="min-h-0 flex-1 overflow-hidden">
            <RolesAndPermissions />
          </TabsContent>
        )}
        {showOrgSyncTab && (
          <TabsContent value="orgSync" className="min-h-0 flex-1 overflow-hidden">
            <OrgSync />
          </TabsContent>
        )}
        {canAccessSystemConfig && (
          <TabsContent value="system" className="min-h-0 flex-1 overflow-hidden">
            <Config />
          </TabsContent>
        )}
        {canAccessSystemConfig && (
          <TabsContent value="theme" className="min-h-0 flex-1 overflow-hidden">
            <Theme />
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
