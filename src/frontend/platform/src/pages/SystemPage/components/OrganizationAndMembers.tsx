import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { Suspense, lazy } from "react"
import { useTranslation } from "react-i18next"
import Users from "./Users"

const Departments = lazy(() => import("./Departments"))

export default function OrganizationAndMembers() {
  const { t } = useTranslation()
  return (
    <Tabs defaultValue="org" className="w-full">
      <TabsList className="mb-2">
        <TabsTrigger value="org">{t("system.orgStructureTab")}</TabsTrigger>
        <TabsTrigger value="users">{t("system.globalUsersTab")}</TabsTrigger>
      </TabsList>
      <TabsContent value="org" className="mt-0">
        <Suspense
          fallback={
            <div className="flex h-40 items-center justify-center text-muted-foreground">
              Loading...
            </div>
          }
        >
          <Departments />
        </Suspense>
      </TabsContent>
      <TabsContent value="users" className="mt-0">
        <Users />
      </TabsContent>
    </Tabs>
  )
}
