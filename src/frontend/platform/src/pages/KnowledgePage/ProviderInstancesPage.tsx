import { Button, Input, toast } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate, useNavigate } from "react-router-dom";
import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import {
  createProviderInstance,
  listProviderInstances,
  updateProviderInstance,
  type ProviderInstance,
} from "@/controllers/API/providerInstances";
import { useKnowledgePageScope } from "@/hooks/useKnowledgePageScope";
import { KnowledgeScopeUnavailable } from "./components/KnowledgeScopeUnavailable";
import { SpacePanelFrame } from "./components/SpacePanelFrame";

const queryKey = ["knowledge", "provider-instances"] as const;

export function ProviderInstancesPage() {
  const { t } = useTranslation("knowledge");
  const navigate = useNavigate();
  const client = useQueryClient();
  const { canManage, isLoading, retry } = useKnowledgePageScope();
  const instances = useQuery({ queryKey, queryFn: listProviderInstances, enabled: canManage && !isLoading });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [endpoint, setEndpoint] = useState("");
  const [workspaceId, setWorkspaceId] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [signedSecret, setSignedSecret] = useState("");
  const [saving, setSaving] = useState(false);
  const back = () => navigate("/filelib");

  if (!isLoading && !canManage) return <Navigate to="/filelib" replace />;

  function beginCreate() {
    setEditingId(null);
    setEndpoint("");
    setWorkspaceId("");
    setApiKey("");
    setSignedSecret("");
  }

  function beginEdit(row: ProviderInstance) {
    setEditingId(row.id);
    setEndpoint(row.endpoint);
    setWorkspaceId(row.remote_scope_id);
    setApiKey("");
    setSignedSecret("");
  }

  async function handleSave() {
    if (saving) return;
    setSaving(true);
    try {
      const shared = { endpoint: endpoint.trim(), remote_scope_id: workspaceId.trim() };
      const secrets = {
        ...(apiKey ? { api_key: apiKey } : {}),
        ...(signedSecret ? { upload_signed_token_secret: signedSecret } : {}),
      };
      if (editingId === null) await createProviderInstance({ ...shared, api_key: apiKey, ...secrets });
      else await updateProviderInstance(editingId, { ...shared, ...secrets });
      await client.invalidateQueries({ queryKey });
      beginCreate();
      toast.show({ type: "success", message: t("providerInstance.saved") });
    } catch {
      // The request wrapper already shows the error.
    } finally {
      setSaving(false);
    }
  }

  const rows = instances.data ?? [];
  return (
    <main className="h-full min-h-0 min-w-0 bg-bg-page">
      <SpacePanelFrame
        title={t("providerInstance.title")}
        presentation="page"
        back={{ label: t("providerInstance.back"), onClick: back }}
        footer={
          <Button variant="outlined" color="default" onClick={back}>
            {t("providerInstance.back")}
          </Button>
        }
      >
        {isLoading || (canManage && !instances.data && !instances.isError) ? (
          <LoadingState size="page" className="h-full" label={t("f118.loading_space")} />
        ) : instances.isError ? (
          <KnowledgeScopeUnavailable action={<Button onClick={() => { void instances.refetch(); void retry(); }}>{t("retry")}</Button>} />
        ) : (
          <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-6 py-4">
            <p className="text-body text-text-2">{t("providerInstance.intro")}</p>
            {rows.length > 1 && <p role="alert" className="text-body text-danger">{t("providerInstance.singleHint")}</p>}
            <div className="flex flex-col gap-3">
              <label className="space-y-1">
                <span className="text-body text-text-1">{t("providerInstance.endpoint")}</span>
                <Input value={endpoint} onChange={(event) => setEndpoint(event.target.value)} />
              </label>
              <label className="space-y-1">
                <span className="text-body text-text-1">{t("providerInstance.workspaceId")}</span>
                <Input value={workspaceId} onChange={(event) => setWorkspaceId(event.target.value)} />
                <p className="text-caption text-text-3">{t("providerInstance.workspaceHint")}</p>
              </label>
              <label className="space-y-1">
                <span className="text-body text-text-1">{t("providerInstance.apiKey")}</span>
                <Input type="password" value={apiKey} autoComplete="new-password" onChange={(event) => setApiKey(event.target.value)} />
                {editingId !== null && <p className="text-caption text-text-3">{t("providerInstance.apiKeyKeep")}</p>}
              </label>
              <label className="space-y-1">
                <span className="text-body text-text-1">{t("providerInstance.signedTokenSecret")}</span>
                <Input
                  type="password"
                  value={signedSecret}
                  autoComplete="new-password"
                  onChange={(event) => setSignedSecret(event.target.value)}
                />
                <p className="text-caption text-text-3">
                  {editingId !== null ? t("providerInstance.signedTokenSecretKeep") : t("providerInstance.signedTokenSecretHint")}
                </p>
              </label>
              <div className="flex gap-2">
                <Button disabled={saving || !endpoint.trim() || !workspaceId.trim() || (editingId === null && !apiKey)} onClick={() => { void handleSave(); }}>
                  {t("providerInstance.save")}
                </Button>
                <Button variant="outlined" color="default" disabled={saving} onClick={beginCreate}>
                  {t("providerInstance.create")}
                </Button>
              </div>
            </div>
            {rows.length === 0 ? (
              <p className="text-body text-text-3">{t("providerInstance.empty")}</p>
            ) : (
              <ul className="flex flex-col gap-2">
                {rows.map((row) => (
                  <li key={row.id}>
                    <button
                      type="button"
                      className="flex w-full flex-col items-start rounded-lg border border-border-base px-4 py-3 text-left hover:bg-fill-1"
                      onClick={() => beginEdit(row)}
                    >
                      <span className="text-body text-text-1">{t("providerInstance.connectionId", { id: row.id })}</span>
                      <span className="text-caption text-text-3">{row.endpoint}</span>
                      <span className="text-caption text-text-3">{row.remote_scope_id}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </SpacePanelFrame>
    </main>
  );
}
