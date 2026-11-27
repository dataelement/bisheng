import { LoadingState } from "@/components/bs-icons/loading/LoadingState";
import { userContext } from "@/contexts/userContext";
import {
  createPermissionCatalogDraftApi,
  getPermissionCatalogApi,
  publishPermissionCatalogDraftApi,
  type PermissionCatalogChange,
  type PermissionCatalogDraft,
  type PermissionCatalogRelease,
  type PublishPermissionCatalogDraftRequest,
} from "@/controllers/API/permission";
import { cn } from "@/utils";
import { Alert, Button, Tabs, toast } from "@bisheng/ui";
import { useCallback, useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Roles from "./Roles";
import { ActionLevelBoard } from "./permission/ActionLevelBoard";
import { ImpactDialog } from "./permission/ImpactDialog";
import { ModelCatalogPanel } from "./permission/ModelEditor";

function createIdempotencyKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function RolesAndPermissions() {
  const { t } = useTranslation("permission");
  const { user } = useContext(userContext);
  const isPlatformSuperAdmin = Boolean(user?.is_global_super) || user?.role === "admin";
  const [catalog, setCatalog] = useState<PermissionCatalogRelease | null>(null);
  const [riskOpen, setRiskOpen] = useState(false);
  const [impact, setImpact] = useState<{
    draft: PermissionCatalogDraft;
    variant?: "modelEdit";
  } | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [headerTarget, setHeaderTarget] = useState<HTMLDivElement | null>(null);

  const loadCatalog = useCallback(async () => {
    if (!isPlatformSuperAdmin) return;
    setLoading(true);
    setLoadFailed(false);
    try {
      setCatalog(await getPermissionCatalogApi());
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, [isPlatformSuperAdmin]);

  useEffect(() => {
    if (isPlatformSuperAdmin) {
      void loadCatalog();
    } else {
      setCatalog(null);
      setRiskOpen(false);
      setImpact(null);
    }
  }, [isPlatformSuperAdmin, loadCatalog]);

  const handleCreateDraft = async (
    changes: PermissionCatalogChange[],
    config: { silent?: boolean } = {},
  ): Promise<PermissionCatalogDraft> => {
    if (!catalog) throw new Error("Permission catalog is not loaded");
    return await createPermissionCatalogDraftApi(
      {
        idempotency_key: createIdempotencyKey("catalog-draft"),
        base_release_id: catalog.id,
        changes,
      },
      config,
    );
  };

  const handleReviewImpact = (draft: PermissionCatalogDraft, variant?: "modelEdit") => {
    setImpact({ draft, variant });
  };

  const handleDeleteModel = async (modelKey: string): Promise<PermissionCatalogDraft> => {
    try {
      return await handleCreateDraft([{ type: "DELETE_MODEL", model_key: modelKey }], { silent: true });
    } catch (error) {
      const detail = (error as { data?: { reason?: string; reference_count?: number } } | null)?.data;
      const message = detail?.reason === "referenced_by_grants"
        ? t("model.deleteBlockedByGrants", { count: detail.reference_count ?? 0 })
        : detail?.reason === "projection_residual"
          ? t("model.deleteBlockedByResidual")
          : t("model.deleteFailed");
      toast.show({ type: "error", message });
      throw error;
    }
  };

  const handlePublish = async (draftId: number, payload: PublishPermissionCatalogDraftRequest) => {
    await publishPermissionCatalogDraftApi(draftId, payload, {});
    setImpact(null);
    setRiskOpen(false);
    await loadCatalog();
    toast.show({ type: "success", message: t("catalog.publishSucceeded") });
  };

  if (!isPlatformSuperAdmin) return <Roles />;

  return (
    <div className="flex h-full min-h-0 min-w-0 flex-col px-1 py-2">
      <Tabs
        defaultActiveKey="menuRoles"
        variant="neutral"
        extra={(
          <div
            ref={setHeaderTarget}
            className={cn(
              "contents [&>p]:col-start-1 [&>p]:row-start-2 [&>p]:pt-4",
              "[&>div]:col-start-1 [&>div]:row-start-3 [&>div]:min-w-0 [&>div]:justify-self-end [&>div]:self-center [&>div]:pt-3",
              "md:[&>div]:col-start-2 md:[&>div]:row-[1/span_2] md:[&>div]:pt-0",
            )}
          />
        )}
        className={cn(
          "grid min-h-0 min-w-0 flex-1 grid-cols-1 grid-rows-[auto_auto_auto_minmax(0,1fr)] gap-x-6",
          "md:grid-cols-[minmax(0,1fr)_auto] md:grid-rows-[auto_auto_minmax(0,1fr)]",
          "[&>div:first-child]:contents [&>div:first-child>div:last-child]:contents",
          "[&>div:first-child>div:first-child]:col-start-1 [&>div:first-child>div:first-child]:row-start-1 [&>div:first-child>div:first-child]:justify-self-start",
          "[&>[role=tabpanel]]:col-span-full [&>[role=tabpanel]]:row-start-4 [&>[role=tabpanel]]:min-h-0 [&>[role=tabpanel]]:min-w-0 [&>[role=tabpanel]]:pt-4 md:[&>[role=tabpanel]]:row-start-3",
          "[&>[role=tabpanel][data-state=active]]:flex [&>[role=tabpanel][data-state=active]]:flex-col",
        )}
        items={[
          {
            key: "menuRoles",
            label: t("catalog.roleConfiguration"),
            children: <Roles headerTarget={headerTarget} />,
          },
          {
            key: "operationPermissions",
            label: t("catalog.permissionConfiguration"),
            children: (
              <>
                {loading && (
                  <LoadingState label={t("catalog.loading")} className="flex min-h-56 items-center justify-center gap-2 text-text-2" />
                )}
                {!loading && loadFailed && (
                  <div className="flex items-center gap-3">
                    <Alert type="error" description={t("catalog.loadFailed")} />
                    <Button type="button" variant="outlined" color="default" onClick={() => void loadCatalog()}>
                      {t("catalog.retry")}
                    </Button>
                  </div>
                )}
                {!loading && !loadFailed && catalog && (
                  <ModelCatalogPanel
                    key={catalog.id}
                    catalog={catalog}
                    headerTarget={headerTarget}
                    onConfigureRisk={() => setRiskOpen(true)}
                    onCreateDraft={handleCreateDraft}
                    onDeleteModel={handleDeleteModel}
                    onReviewImpact={handleReviewImpact}
                  />
                )}
              </>
            ),
          },
        ]}
      />

      {!loadFailed && catalog && (
        <ActionLevelBoard
          actions={catalog.actions}
          open={riskOpen}
          onOpenChange={setRiskOpen}
          onCreateDraft={handleCreateDraft}
          onReviewImpact={handleReviewImpact}
        />
      )}
      <ImpactDialog
        key={impact?.draft.draft_id}
        open={impact !== null}
        draft={impact?.draft ?? null}
        variant={impact?.variant}
        models={catalog?.models}
        actions={catalog?.actions}
        onOpenChange={(open) => { if (!open) setImpact(null); }}
        onPublish={handlePublish}
      />
    </div>
  );
}
