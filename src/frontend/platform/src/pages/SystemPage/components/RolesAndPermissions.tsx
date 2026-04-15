import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { userContext } from "@/contexts/userContext"
import { getRebacSchemaApi, RebacSchemaType } from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { useContext, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import Roles from "./Roles"

export default function RolesAndPermissions() {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  const [types, setTypes] = useState<RebacSchemaType[] | null>(null)

  useEffect(() => {
    if (user?.role !== "admin") {
      setTypes([])
      return
    }
    captureAndAlertRequestErrorHoc(getRebacSchemaApi()).then((res) => {
      if (res?.types) setTypes(res.types)
      else if (res) setTypes([])
    })
  }, [user?.role])

  return (
    <Tabs defaultValue="roles" className="w-full">
      <TabsList className="mb-2">
        <TabsTrigger value="roles">{t("system.roleManagement")}</TabsTrigger>
        <TabsTrigger value="rebac" disabled={user?.role !== "admin"}>
          {t("system.rebacSchemaTab")}
        </TabsTrigger>
      </TabsList>
      <TabsContent value="roles" className="mt-0">
        <Roles />
      </TabsContent>
      <TabsContent value="rebac" className="mt-0">
        <div className="h-[calc(100vh-140px)] overflow-auto pb-6 pt-2">
          <p className="mb-4 text-sm text-muted-foreground">
            {t("system.rebacSchemaReadonly")}
          </p>
          {user?.role !== "admin" ? (
            <p className="text-sm text-muted-foreground">{t("system.rebacAdminOnly")}</p>
          ) : types === null ? (
            <p className="text-sm text-muted-foreground">…</p>
          ) : types.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("build.empty")}</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[220px]">type</TableHead>
                  <TableHead>relations</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {types.map((row) => (
                  <TableRow key={row.type}>
                    <TableCell className="align-top font-mono text-xs">
                      {row.type}
                    </TableCell>
                    <TableCell className="text-xs">
                      {row.relations.join(", ")}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
      </TabsContent>
    </Tabs>
  )
}
