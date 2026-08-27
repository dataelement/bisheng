import { Button } from "@/components/bs-ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { message } from "@/components/bs-ui/toast/use-toast"
import { userContext } from "@/contexts/userContext"
import {
  createPermissionCatalogDraftApi,
  getPermissionCatalogApi,
  publishPermissionCatalogDraftApi,
  type PermissionCatalogChange,
  type PermissionCatalogDraft,
  type PermissionCatalogRelease,
  type PermissionCatalogModel,
  type PublishPermissionCatalogDraftRequest,
} from "@/controllers/API/permission"
import { AlertTriangle, Plus, RefreshCw } from "lucide-react"
import { useCallback, useContext, useEffect, useState } from "react"
import { useTranslation } from "react-i18next"
import Roles from "./Roles"
import { ActionLevelBoard } from "./permission/ActionLevelBoard"
import { ImpactDialog } from "./permission/ImpactDialog"
import { ModelEditor } from "./permission/ModelEditor"

function createIdempotencyKey(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

interface CatalogStateProps {
  loading: boolean
  error: boolean
  onRetry: () => void
}

function CatalogState({ loading, error, onRetry }: CatalogStateProps) {
  const { t } = useTranslation("permission")

  if (loading) {
    return (
      <div className="flex min-h-56 items-center justify-center gap-2 text-sm text-muted-foreground">
        <RefreshCw aria-hidden="true" className="size-4 animate-spin" />
        {t("catalog.loading")}
      </div>
    )
  }
  if (error) {
    return (
      <div
        className="flex min-h-56 flex-col items-center justify-center gap-3 rounded-xl border border-red-200 bg-red-50 p-6 text-red-900"
        role="alert"
      >
        <AlertTriangle aria-hidden="true" className="size-5" />
        <p className="text-sm font-medium">{t("catalog.loadFailed")}</p>
        <Button
          type="button"
          variant="outline"
          className="bg-background"
          onClick={onRetry}
        >
          {t("catalog.retry")}
        </Button>
      </div>
    )
  }
  return null
}

interface ModelCatalogPanelProps {
  catalog: PermissionCatalogRelease
  selectedModelKey: string | null
  onSelectModel: (modelKey: string) => void
  onCreateDraft: (
    changes: PermissionCatalogChange[],
  ) => Promise<PermissionCatalogDraft>
  onDeleteModel: (modelKey: string) => Promise<PermissionCatalogDraft>
  onReviewImpact: (draft: PermissionCatalogDraft) => void
}

const NEW_CUSTOM_MODEL: PermissionCatalogModel = {
  key: "__new_custom_model__",
  name: "",
  kind: "CUSTOM",
  config_scope: "PLATFORM",
  derived_level: null,
  active: true,
  allow_same_level: false,
  action_codes: [],
  version: 0,
}

function ModelCatalogPanel({
  catalog,
  selectedModelKey,
  onSelectModel,
  onCreateDraft,
  onDeleteModel,
  onReviewImpact,
}: ModelCatalogPanelProps) {
  const { t } = useTranslation("permission")
  const [creating, setCreating] = useState(false)
  const selectedModel = creating
    ? NEW_CUSTOM_MODEL
    : (catalog.models.find((model) => model.key === selectedModelKey) ??
      catalog.models[0] ??
      null)

  useEffect(() => {
    setCreating(false)
  }, [catalog.id])

  return (
    <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[16rem_minmax(0,1fr)]">
      <aside
        aria-label={t("model.list")}
        className="flex min-h-0 flex-col rounded-xl border bg-muted/20 p-3"
      >
        <div className="flex items-center justify-between gap-2 px-2 pb-3">
          <h2 className="text-sm font-semibold text-foreground">
            {t("model.list")}
          </h2>
          <Button
            type="button"
            variant="outline"
            className="px-2"
            aria-pressed={creating}
            onClick={() => setCreating(true)}
          >
            <Plus aria-hidden="true" className="mr-1 size-4" />
            {t("model.create")}
          </Button>
        </div>
        {/* The list scrolls on its own so the editor beside it keeps its own scrollbar. */}
        <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto">
          {catalog.models.map((model: PermissionCatalogModel) => (
            <button
              key={model.key}
              type="button"
              aria-pressed={!creating && selectedModel?.key === model.key}
              onClick={() => {
                setCreating(false)
                onSelectModel(model.key)
              }}
              // Two lines of text in a fixed-height row sat against the top edge;
              // centre them so the selected block reads as one item.
              className="flex min-h-[52px] flex-col justify-center rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-muted aria-pressed:bg-primary aria-pressed:text-primary-foreground"
            >
              <span className="block truncate font-medium">{model.name}</span>
              {/* The row used to repeat only "standard / custom". What the author
                  actually looks for is the tier and whether it is switched on. */}
              <span className="block truncate text-xs opacity-70">
                {t(`model.kind.${model.kind.toLowerCase()}`)}
                {" · "}
                {model.derived_level === null
                  ? t("actionLevel.unassigned")
                  : t("actionLevel.level", { level: model.derived_level })}
                {!model.active && ` · ${t("model.inactive")}`}
              </span>
            </button>
          ))}
        </div>
      </aside>

      {selectedModel ? (
        <ModelEditor
          model={selectedModel}
          actions={catalog.actions}
          presets={catalog.presets ?? []}
          createMode={creating}
          onCreateDraft={onCreateDraft}
          onDeleteModel={onDeleteModel}
          onReviewImpact={onReviewImpact}
        />
      ) : (
        <p className="min-h-0 rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
          {t("model.empty")}
        </p>
      )}
    </div>
  )
}

export function RolesAndPermissions() {
  const { t } = useTranslation("permission")
  const { user } = useContext(userContext)
  const isPlatformSuperAdmin =
    Boolean(user?.is_global_super) || user?.role === "admin"
  const [catalog, setCatalog] = useState<PermissionCatalogRelease | null>(null)
  const [selectedModelKey, setSelectedModelKey] = useState<string | null>(null)
  const [impactDraft, setImpactDraft] =
    useState<PermissionCatalogDraft | null>(null)
  const [impactOpen, setImpactOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [loadFailed, setLoadFailed] = useState(false)

  const loadCatalog = useCallback(async () => {
    if (!isPlatformSuperAdmin) return
    setLoading(true)
    setLoadFailed(false)
    try {
      const release = await getPermissionCatalogApi()
      setCatalog(release)
      setSelectedModelKey((current) =>
        release.models.some((model) => model.key === current)
          ? current
          : (release.models[0]?.key ?? null),
      )
    } catch {
      setLoadFailed(true)
    } finally {
      setLoading(false)
    }
  }, [isPlatformSuperAdmin])

  useEffect(() => {
    if (isPlatformSuperAdmin) void loadCatalog()
    else {
      setCatalog(null)
      setSelectedModelKey(null)
    }
  }, [isPlatformSuperAdmin, loadCatalog])

  const handleCreateDraft = async (
    changes: PermissionCatalogChange[],
    config: { silent?: boolean } = {},
  ): Promise<PermissionCatalogDraft> => {
    if (!catalog) throw new Error("permission Catalog is not loaded")
    return await createPermissionCatalogDraftApi(
      {
        idempotency_key: createIdempotencyKey("catalog-draft"),
        base_release_id: catalog.id,
        changes,
      },
      config,
    )
  }

  const handleReviewImpact = (draft: PermissionCatalogDraft) => {
    setImpactDraft(draft)
    setImpactOpen(true)
  }

  const handleDeleteModel = async (
    modelKey: string,
  ): Promise<PermissionCatalogDraft> => {
    if (!catalog) throw new Error("permission Catalog is not loaded")
    try {
      return await handleCreateDraft(
        [{ type: "DELETE_MODEL", model_key: modelKey }],
        { silent: true },
      )
    } catch (error) {
      // Nothing else reports this: the request layer only auto-toasts a couple of
      // special codes, and a failed publish would otherwise close the dialog and
      // leave the model in place with no explanation. 25004 covers several model
      // -state conflicts, so name the one in the way — "state does not allow
      // this" leaves the author with nothing to act on.
      const detail = (
        error as { data?: { reason?: string; reference_count?: number } } | null
      )?.data
      message({
        variant: "error",
        description:
          detail?.reason === "referenced_by_grants"
            ? t("model.deleteBlockedByGrants", { count: detail.reference_count ?? 0 })
            : detail?.reason === "projection_residual"
              ? t("model.deleteBlockedByResidual")
            : t("model.deleteFailed"),
      })
      throw error
    }
  }

  const handlePublish = async (
    draftId: number,
    payload: PublishPermissionCatalogDraftRequest,
    config: { silent?: boolean } = {},
  ) => {
    await publishPermissionCatalogDraftApi(draftId, payload, config)
    setImpactDraft(null)
    await loadCatalog()
    message({
      variant: "success",
      description: t("catalog.publishSucceeded"),
    })
  }

  return (
    <div className="flex h-full min-h-0 flex-col py-2">
      <Tabs
        defaultValue="menuRoles"
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="h-auto min-h-[44px] shrink-0 self-start">
          <TabsTrigger className="min-h-9" value="menuRoles">
            {t("catalog.menuRoles")}
          </TabsTrigger>
          {isPlatformSuperAdmin && (
            <>
              <TabsTrigger className="min-h-9" value="actions">
                {t("catalog.actions")}
              </TabsTrigger>
              <TabsTrigger className="min-h-9" value="models">
                {t("catalog.models")}
              </TabsTrigger>
            </>
          )}
        </TabsList>

        {/* Three sibling tabs that look interchangeable but are not: menu roles
            gate pages, the other two gate what a user may do to a resource. */}
        {isPlatformSuperAdmin && (
          <p className="mt-2 shrink-0 text-xs leading-5 text-muted-foreground">
            {t("catalog.hint")}
          </p>
        )}

        <TabsContent
          value="menuRoles"
          className="min-h-0 flex-1 overflow-auto"
        >
          <Roles />
        </TabsContent>

        {isPlatformSuperAdmin && (
          <>
            {/* overflow-hidden, not auto: each board owns its single scroll area,
                otherwise the tab pane scrolls on top of it. */}
            <TabsContent
              value="actions"
              className="flex min-h-0 flex-1 flex-col overflow-hidden py-2"
            >
              <CatalogState
                loading={loading}
                error={loadFailed}
                onRetry={() => void loadCatalog()}
              />
              {!loading && !loadFailed && catalog && (
                <ActionLevelBoard
                  actions={catalog.actions}
                  onCreateDraft={handleCreateDraft}
                  onReviewImpact={handleReviewImpact}
                />
              )}
            </TabsContent>
            <TabsContent
              value="models"
              className="flex min-h-0 flex-1 flex-col overflow-hidden py-2"
            >
              <CatalogState
                loading={loading}
                error={loadFailed}
                onRetry={() => void loadCatalog()}
              />
              {!loading && !loadFailed && catalog && (
                <ModelCatalogPanel
                  catalog={catalog}
                  selectedModelKey={selectedModelKey}
                  onSelectModel={setSelectedModelKey}
                  onCreateDraft={handleCreateDraft}
                  onDeleteModel={handleDeleteModel}
                  onReviewImpact={handleReviewImpact}
                />
              )}
            </TabsContent>
          </>
        )}
      </Tabs>

      <ImpactDialog
        open={impactOpen}
        draft={impactDraft}
        models={catalog?.models}
        actions={catalog?.actions}
        onOpenChange={setImpactOpen}
        onPublish={handlePublish}
      />
    </div>
  )
}
