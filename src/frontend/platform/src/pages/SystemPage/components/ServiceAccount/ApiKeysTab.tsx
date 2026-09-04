import { Badge } from "@/components/bs-ui/badge"
import { Button } from "@/components/bs-ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/bs-ui/table"
import {
  listOpenApiScopesApi,
  listServiceAccountKeysApi,
  revokeServiceAccountKeyApi,
} from "@/controllers/API/serviceAccount"
import type { ApiKeyItem, OpenApiScopeItem } from "@/types/api/openApi"
import { useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import { KeyIssueDialog } from "./KeyIssueDialog"

export interface ApiKeysTabProps {
  serviceAccountId: number
}

export function ApiKeysTab({ serviceAccountId }: ApiKeysTabProps) {
  const { t } = useTranslation()
  const [keys, setKeys] = useState<ApiKeyItem[]>([])
  const [scopes, setScopes] = useState<OpenApiScopeItem[]>([])
  const [dialogOpen, setDialogOpen] = useState(false)

  const loadKeys = async () => setKeys(await listServiceAccountKeysApi(serviceAccountId))

  useEffect(() => {
    void listServiceAccountKeysApi(serviceAccountId).then(setKeys)
    void listOpenApiScopesApi().then((catalog) => setScopes(catalog.scopes))
  }, [serviceAccountId])

  const handleRevoke = async (keyId: number) => {
    await revokeServiceAccountKeyApi(serviceAccountId, keyId)
    await loadKeys()
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button onClick={() => setDialogOpen(true)}>{t("openApiManagement.keys.issue")}</Button>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("openApiManagement.fields.name")}</TableHead>
            <TableHead>{t("openApiManagement.keys.mask")}</TableHead>
            <TableHead>{t("openApiManagement.keys.permissions")}</TableHead>
            <TableHead>{t("openApiManagement.keys.delegateScopes")}</TableHead>
            <TableHead>{t("openApiManagement.fields.status")}</TableHead>
            <TableHead className="text-right">{t("operations")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {keys.map((key) => (
            <TableRow key={key.id}>
              <TableCell>{key.name}</TableCell>
              <TableCell><code>{key.key_mask}</code></TableCell>
              <TableCell>{key.scopes.join(", ")}</TableCell>
              <TableCell>{key.delegate_scopes.map((scope) => `${scope.subject_type}:${scope.subject_id}`).join(", ") || "-"}</TableCell>
              <TableCell><Badge variant={key.is_valid ? "outline" : "secondary"}>{t(key.is_valid ? "openApiManagement.status.active" : "openApiManagement.status.revoked")}</Badge></TableCell>
              <TableCell className="text-right">
                <Button variant="link" disabled={!key.is_valid} onClick={() => handleRevoke(key.id)}>
                  {t("openApiManagement.actions.revoke")}
                </Button>
              </TableCell>
            </TableRow>
          ))}
          {!keys.length ? (
            <TableRow><TableCell colSpan={6} className="text-center text-muted-foreground">{t("openApiManagement.empty")}</TableCell></TableRow>
          ) : null}
        </TableBody>
      </Table>
      <KeyIssueDialog
        serviceAccountId={serviceAccountId}
        scopes={scopes}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        onIssued={loadKeys}
      />
    </div>
  )
}
