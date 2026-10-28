import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import { Tabs } from "@bisheng/ui";
import { useContext } from "react";
import { useTranslation } from "react-i18next";
import Config from "./components/Config";
import OrganizationAndMembers from "./components/OrganizationAndMembers";
import OrgSync from "./components/OrgSync";
import { PersonalToken } from "./components/PersonalToken";
import { RolesAndPermissions } from "./components/RolesAndPermissions";
import { ServiceAccount } from "./components/ServiceAccount";
import UserGroups from "./components/UserGroup";
import Users from "./components/Users";
import Theme from "./theme";
import { ResourceTierTab } from "./components/ResourceTierTab";

export default function SystemPage() {
  const { user } = useContext(userContext);
  const { appConfig } = useContext(locationContext);

  const { t } = useTranslation();
  const isSuperAdmin = user?.role === "admin";
  const isDeptAdmin = !!user?.is_department_admin;
  const isChildAdmin = !!user?.is_child_admin;
  /** PRD §3.3: org tab is per-Tenant. Super admin sees full tree;
   *  Child Admin manages own Child; dept admin manages own subtree. */
  const showOrgTab = isSuperAdmin || isDeptAdmin || isChildAdmin;
  /** PRD §3.3 / §5.5: role mgmt scoped to admins (super / Child / dept). */
  const showRoleTab = isSuperAdmin || isDeptAdmin || isChildAdmin;
  /** System config edits instance-level config.yaml; theme writes
   *  instance-level CSS vars/logo. Neither has per-Tenant semantics,
   *  so restrict to global super admin only. */
  const canAccessSystemConfig = isSuperAdmin;
  /** Organization sync is read-only here and visible only to global administrators. */
  const showOrgSyncTab = isSuperAdmin;
  /** PRD §4.5: Child Admin manages own tenant's user groups. Backend now
   *  flips can_manage_user_groups true for Child Admin too; the explicit
   *  is_child_admin term keeps the tab visible if the backend regresses. */
  const showUserGroupTab = user?.role === "admin" || !!user?.can_manage_user_groups || !!user?.is_child_admin;
  /** Legacy flat user table is for accounts without org-tab access. */
  const showLegacyUserTab = !showOrgTab;
  /** F053 service accounts + personal tokens. Admin rights are necessary but not
   *  sufficient: the console stays hidden until the deployment opts in, so a
   *  release can ship the backend while the surface is still being built. */
  const showOpenApiManagement =
    (isSuperAdmin || isChildAdmin) && !!appConfig?.openApiManagementEnabled
  /** F055 AC-45: resource tiers are platform-level (shared across tenants), so
   *  super admin only — and only where the app-factory runtime layer is
   *  deployed; without it there is nothing the tiers would apply to. */
  const showResourceTierTab = isSuperAdmin && !!appConfig?.appRuntimeEnabled

  const defaultTab = showOrgTab ? "organization" : showUserGroupTab ? "userGroup" : "user";

  return (
    <div className="flex h-full w-full flex-col px-4 pt-4">
      <Tabs
        defaultActiveKey={defaultTab}
        className="flex min-h-0 w-full flex-1 flex-col [&>div:first-child]:shrink-0 [&>[role=tabpanel][data-state=active]]:flex [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:flex-1 [&>[role=tabpanel]]:flex-col [&>[role=tabpanel]]:overflow-hidden [&>[role=tabpanel]>div]:mt-2"
        items={[
          ...(showOrgTab
            ? [
                {
                  key: "organization",
                  label: <> {t("system.orgAndMembers")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <OrganizationAndMembers />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(showLegacyUserTab
            ? [
                {
                  key: "user",
                  label: <> {t("system.userManagement")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <Users />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(showUserGroupTab
            ? [
                {
                  key: "userGroup",
                  label: <> {t("system.userGroupsM")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <UserGroups />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(showRoleTab
            ? [
                {
                  key: "role",
                  label: <> {t("system.roleAndPermissions")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <RolesAndPermissions />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(showOrgSyncTab
            ? [
                {
                  key: "orgSync",
                  label: <> {t("orgSync:title")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <OrgSync />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(showOpenApiManagement
            ? [
                {
                  key: "serviceAccount",
                  label: <> {t("openApiManagement.serviceAccount.title")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <ServiceAccount />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(showOpenApiManagement
            ? [
                {
                  key: "personalToken",
                  label: <> {t("openApiManagement.personalToken.title")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <PersonalToken />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(showResourceTierTab ? [{
            key: "resourceTier",
            label: t("hostedApp.tierAdmin.title"),
            children: <div className="min-h-0 flex-1 overflow-hidden"><ResourceTierTab /></div>,
          }] : []),
          ...(canAccessSystemConfig
            ? [
                {
                  key: "system",
                  label: <> {t("system.systemConfiguration")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <Config />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
          ...(canAccessSystemConfig
            ? [
                {
                  key: "theme",
                  label: <> {t("system.appearanceSettings")} </>,
                  children: (
                    <>
                      {" "}
                      <div className="min-h-0 flex-1 overflow-hidden">
                        <Theme />
                      </div>
                    </>
                  ),
                },
              ]
            : []),
        ]}
      />
    </div>
  );
}
