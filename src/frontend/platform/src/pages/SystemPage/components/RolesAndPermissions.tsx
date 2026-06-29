import {
  Button,
} from "@/components/bs-ui/button"
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/bs-ui/dialog"
import {
  Checkbox,
} from "@/components/bs-ui/checkBox"
import { Input } from "@/components/bs-ui/input"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/bs-ui/tabs"
import { userContext } from "@/contexts/userContext"
import {
  getApplicationPermissionTemplateApi,
  createRelationModelApi,
  deleteRelationModelApi,
  getChannelPermissionTemplateApi,
  getKnowledgeLibraryPermissionTemplateApi,
  getKnowledgeSpacePermissionTemplateApi,
  getRebacSchemaApi,
  getRelationModelsApi,
  getToolPermissionTemplateApi,
  type PermissionTemplateSection,
  type RebacSchemaType,
  type RelationModel,
  updateRelationModelApi,
} from "@/controllers/API/permission"
import { captureAndAlertRequestErrorHoc } from "@/controllers/request"
import { message } from "@/components/bs-ui/toast/use-toast"
import { useContext, useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import Roles from "./Roles"

type TemplatePermission = { id: string; label: string; relation: string }
type TemplateSection = { title: string; columns: { title: string; items: TemplatePermission[] }[] }

const HIDDEN_RELATION_PERMISSION_IDS = new Set(["share_folder", "share_file"])

const RELATION_LEVEL: Record<string, number> = {
  viewer: 1,
  can_read: 1,
  editor: 2,
  can_edit: 2,
  manager: 3,
  can_manage: 3,
  owner: 4,
  can_delete: 4,
}

// Manage permissions form a hierarchy per resource type: owner ⊃ manager ⊃ viewer.
// Selecting a higher tier implies all lower tiers; deselecting a lower tier
// must also drop the higher tiers that imply it.
const MANAGE_PERMISSION_IMPLIES: Record<string, string[]> = {
  manage_app_owner: ["manage_app_manager", "manage_app_viewer"],
  manage_app_manager: ["manage_app_viewer"],
  manage_kb_owner: ["manage_kb_manager", "manage_kb_viewer"],
  manage_kb_manager: ["manage_kb_viewer"],
  manage_tool_owner: ["manage_tool_manager", "manage_tool_viewer"],
  manage_tool_manager: ["manage_tool_viewer"],
  manage_channel_owner: ["manage_channel_manager", "manage_channel_user"],
  manage_channel_manager: ["manage_channel_user"],
}
const MODEL_LEVEL: Record<"owner" | "manager" | "editor" | "viewer", number> = {
  viewer: 1,
  editor: 2,
  manager: 3,
  owner: 4,
}

type ModelRelation = keyof typeof MODEL_LEVEL

const RELATION_LEVEL_I18N_KEY: Record<ModelRelation, string> = {
  owner: "system.relationModelLevelOwner",
  manager: "system.relationModelLevelManager",
  editor: "system.relationModelLevelEditor",
  viewer: "system.relationModelLevelViewer",
}

const normalizeRelationModelName = (name: string) => name.trim()

const relationModelNameExists = (models: RelationModel[], name: string, excludeModelId?: string) => {
  const normalizedName = normalizeRelationModelName(name)
  if (!normalizedName) return false
  return models.some((model) => (
    model.id !== excludeModelId
    && normalizeRelationModelName(model.name) === normalizedName
  ))
}

const DEFAULT_RELATION_MODELS: RelationModel[] = [
  { id: "owner", name: "所有者", relation: "owner", grant_tier: "owner", permissions: [], permissions_explicit: false, is_system: true },
  { id: "manager", name: "可管理", relation: "manager", grant_tier: "manager", permissions: [], permissions_explicit: false, is_system: true },
  { id: "editor", name: "可编辑", relation: "editor", grant_tier: "usage", permissions: [], permissions_explicit: false, is_system: true },
  { id: "viewer", name: "可查看", relation: "viewer", grant_tier: "usage", permissions: [], permissions_explicit: false, is_system: true },
]

const filterHiddenTemplatePermissions = (section: TemplateSection): TemplateSection => ({
  ...section,
  columns: section.columns.map((column) => ({
    ...column,
    items: column.items.filter((item) => !HIDDEN_RELATION_PERMISSION_IDS.has(item.id)),
  })),
})

const filterHiddenPermissionIds = (permissionIds: string[]) =>
  permissionIds.filter((id) => !HIDDEN_RELATION_PERMISSION_IDS.has(id))

const CHANNEL_OPERATION_PERMISSION_IDS = new Set([
  "view_channel",
  "edit_channel",
  "delete_channel",
])

const DEPRECATED_CHANNEL_PERMISSION_IDS = new Set([
  "create_channel",
])

const CHANNEL_MEMBER_MANAGEMENT_PERMISSION_IDS = new Set([
  "manage_channel_owner",
  "manage_channel_manager",
  "manage_channel_user",
])

const groupChannelTemplatePermissions = (section: TemplateSection): TemplateSection => {
  const items = section.columns
    .flatMap((column) => column.items)
    .filter((item) => !DEPRECATED_CHANNEL_PERMISSION_IDS.has(item.id))
  const operationItems = items.filter((item) => CHANNEL_OPERATION_PERMISSION_IDS.has(item.id))
  const memberManagementItems = items.filter((item) => CHANNEL_MEMBER_MANAGEMENT_PERMISSION_IDS.has(item.id))
  const groupedIds = new Set([
    ...CHANNEL_OPERATION_PERMISSION_IDS,
    ...CHANNEL_MEMBER_MANAGEMENT_PERMISSION_IDS,
    ...DEPRECATED_CHANNEL_PERMISSION_IDS,
  ])
  const remainingColumns = section.columns
    .map((column) => ({
      ...column,
      items: column.items.filter((item) => !groupedIds.has(item.id)),
    }))
    .filter((column) => column.items.length > 0)

  return {
    ...section,
    columns: [
      ...(operationItems.length > 0 ? [{ title: "频道操作", items: operationItems }] : []),
      ...(memberManagementItems.length > 0 ? [{ title: "成员权限管理", items: memberManagementItems }] : []),
      ...remainingColumns,
    ],
  }
}

/** Fallback when permission template APIs are unavailable; labels are resolved via i18n by permission id. */
const TEMPLATE_SECTIONS: TemplateSection[] = [
  {
    title: "知识空间模块",
    columns: [
      {
        title: "空间级",
        items: [
          { id: "view_space", label: "", relation: "can_read" },
          { id: "edit_space", label: "", relation: "can_edit" },
          { id: "delete_space", label: "", relation: "can_delete" },
          { id: "share_space", label: "", relation: "can_manage" },
          { id: "manage_space_relation", label: "", relation: "can_manage" },
        ],
      },
      {
        title: "文件夹级",
        items: [
          { id: "view_folder", label: "", relation: "can_read" },
          { id: "create_folder", label: "", relation: "can_edit" },
          { id: "rename_folder", label: "", relation: "can_edit" },
          { id: "delete_folder", label: "", relation: "can_delete" },
          { id: "download_folder", label: "", relation: "can_read" },
          { id: "move_folder", label: "", relation: "can_edit" },
          { id: "manage_folder_relation", label: "", relation: "can_manage" },
        ],
      },
      {
        title: "文件级",
        items: [
          { id: "view_file", label: "", relation: "can_read" },
          { id: "upload_file", label: "", relation: "can_edit" },
          { id: "rename_file", label: "", relation: "can_edit" },
          { id: "delete_file", label: "", relation: "can_delete" },
          { id: "download_file", label: "", relation: "can_read" },
          { id: "move_file", label: "", relation: "can_edit" },
          { id: "share_file", label: "", relation: "can_manage" },
          { id: "manage_file_relation", label: "", relation: "can_manage" },
        ],
      },
    ],
  },
  {
    title: "应用/工作流模块",
    columns: [
      {
        title: "",
        items: [
          { id: "view_app", label: "", relation: "can_read" },
          { id: "use_app", label: "", relation: "can_read" },
          { id: "edit_app", label: "", relation: "can_edit" },
          { id: "delete_app", label: "", relation: "can_delete" },
        ],
      },
      {
        title: "",
        items: [
          { id: "publish_app", label: "", relation: "can_manage" },
          { id: "unpublish_app", label: "", relation: "can_manage" },
          { id: "share_app", label: "", relation: "can_manage" },
        ],
      },
      {
        title: "",
        items: [
          { id: "manage_app_owner", label: "", relation: "can_manage" },
          { id: "manage_app_manager", label: "", relation: "can_manage" },
          { id: "manage_app_viewer", label: "", relation: "can_manage" },
        ],
      },
    ],
  },
  {
    title: "知识库模块",
    columns: [
      {
        title: "",
        items: [
          { id: "view_kb", label: "", relation: "can_read" },
          { id: "use_kb", label: "", relation: "can_read" },
          { id: "edit_kb", label: "", relation: "can_edit" },
          { id: "delete_kb", label: "", relation: "can_delete" },
        ],
      },
      {
        title: "",
        items: [
          { id: "manage_kb_owner", label: "", relation: "can_manage" },
          { id: "manage_kb_manager", label: "", relation: "can_manage" },
          { id: "manage_kb_viewer", label: "", relation: "can_manage" },
        ],
      },
    ],
  },
  {
    title: "频道模块",
    columns: [
      {
        title: "频道级",
        items: [
          { id: "view_channel", label: "", relation: "can_read" },
          { id: "edit_channel", label: "", relation: "can_edit" },
          { id: "delete_channel", label: "", relation: "can_delete" },
          { id: "manage_channel_owner", label: "", relation: "owner" },
          { id: "manage_channel_manager", label: "", relation: "owner" },
          { id: "manage_channel_user", label: "", relation: "can_manage" },
        ],
      },
    ],
  },
]

/** Known permission ids from backend templates; others display `item.label` from API (tests / forward compat). */
const PERMISSION_TEMPLATE_IDS = new Set<string>([
  "view_space",
  "edit_space",
  "delete_space",
  "share_space",
  "manage_space_relation",
  "view_folder",
  "create_folder",
  "rename_folder",
  "delete_folder",
  "download_folder",
  "move_folder",
  "manage_folder_relation",
  "view_file",
  "upload_file",
  "rename_file",
  "delete_file",
  "download_file",
  "move_file",
  "share_file",
  "manage_file_relation",
  "view_app",
  "use_app",
  "edit_app",
  "delete_app",
  "publish_app",
  "unpublish_app",
  "share_app",
  "manage_app_owner",
  "manage_app_manager",
  "manage_app_viewer",
  "view_kb",
  "use_kb",
  "edit_kb",
  "delete_kb",
  "manage_kb_owner",
  "manage_kb_manager",
  "manage_kb_viewer",
  "view_tool",
  "use_tool",
  "edit_tool",
  "delete_tool",
  "manage_tool_owner",
  "manage_tool_manager",
  "manage_tool_viewer",
  "view_channel",
  "edit_channel",
  "delete_channel",
  "manage_channel_owner",
  "manage_channel_manager",
  "manage_channel_user",
])

const SECTION_TITLE_I18N_KEY: Readonly<Record<string, string>> = {
  "知识空间模块": "system.permissionTemplate.sectionKnowledgeSpace",
  "应用/工作流模块": "system.permissionTemplate.sectionApplication",
  "知识库模块": "system.permissionTemplate.sectionKnowledgeLibrary",
  "工具模块": "system.permissionTemplate.sectionTool",
  "频道模块": "system.permissionTemplate.sectionChannel",
}

const COLUMN_TITLE_I18N_KEY: Readonly<Record<string, string>> = {
  "空间级": "system.permissionTemplate.columnSpaceLevel",
  "文件夹级": "system.permissionTemplate.columnFolderLevel",
  "文件级": "system.permissionTemplate.columnFileLevel",
  "频道级": "system.permissionTemplate.columnChannelLevel",
  "频道操作": "system.permissionTemplate.columnChannelOperation",
  "成员权限管理": "system.permissionTemplate.columnChannelMemberManagement",
}

function templateSectionTitle(title: string, t: (key: string) => string): string {
  const key = SECTION_TITLE_I18N_KEY[title]
  return key ? t(key) : title
}

function templateColumnTitle(title: string, t: (key: string) => string): string {
  if (!title) return ""
  const key = COLUMN_TITLE_I18N_KEY[title]
  return key ? t(key) : title
}

function templatePermissionLabel(item: TemplatePermission, t: (key: string) => string): string {
  if (!PERMISSION_TEMPLATE_IDS.has(item.id)) return item.label || item.id
  return t(`system.permissionTemplate.${item.id}`)
}

export default function RolesAndPermissions() {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  /** 与系统其它处一致：platform `role === "admin"` 为超级管理员 */
  const isSuperAdmin = user?.role === "admin"
  const [types, setTypes] = useState<RebacSchemaType[] | null>(null)
  const [applicationTemplate, setApplicationTemplate] = useState<PermissionTemplateSection | null>(null)
  const [knowledgeTemplate, setKnowledgeTemplate] = useState<PermissionTemplateSection | null>(null)
  const [knowledgeLibraryTemplate, setKnowledgeLibraryTemplate] = useState<PermissionTemplateSection | null>(null)
  const [toolTemplate, setToolTemplate] = useState<PermissionTemplateSection | null>(null)
  const [channelTemplate, setChannelTemplate] = useState<PermissionTemplateSection | null>(null)
  const [relationModels, setRelationModels] = useState<RelationModel[]>([])
  const [modelId, setModelId] = useState<string>("owner")
  const [selectedPermissionIds, setSelectedPermissionIds] = useState<string[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [newModelName, setNewModelName] = useState("")
  const [newCreateRelation, setNewCreateRelation] = useState<ModelRelation>("viewer")

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

  useEffect(() => {
    if (user?.role !== "admin") return
    captureAndAlertRequestErrorHoc(getRelationModelsApi(), () => true).then((res) => {
      if (res === false) {
        setRelationModels(DEFAULT_RELATION_MODELS)
        setModelId("owner")
        return
      }
      if (!res) return
      setRelationModels(res)
      if (res.length > 0) setModelId((prev) => (res.some((m) => m.id === prev) ? prev : res[0].id))
    })
  }, [user?.role])

  useEffect(() => {
    if (user?.role !== "admin") {
      setApplicationTemplate(null)
      setKnowledgeTemplate(null)
      setKnowledgeLibraryTemplate(null)
      setToolTemplate(null)
      setChannelTemplate(null)
      return
    }
    captureAndAlertRequestErrorHoc(getApplicationPermissionTemplateApi(), () => true).then((res) => {
      if (res) setApplicationTemplate(res)
    })
    captureAndAlertRequestErrorHoc(getKnowledgeSpacePermissionTemplateApi(), () => true).then((res) => {
      if (res) setKnowledgeTemplate(res)
    })
    captureAndAlertRequestErrorHoc(getKnowledgeLibraryPermissionTemplateApi(), () => true).then((res) => {
      if (res) setKnowledgeLibraryTemplate(res)
    })
    captureAndAlertRequestErrorHoc(getToolPermissionTemplateApi(), () => true).then((res) => {
      if (res) setToolTemplate(res)
    })
    captureAndAlertRequestErrorHoc(getChannelPermissionTemplateApi(), () => true).then((res) => {
      if (res) setChannelTemplate(res)
    })
  }, [user?.role])

  const templateSections = useMemo<TemplateSection[]>(() => {
    const sections: TemplateSection[] = [
      (knowledgeTemplate || TEMPLATE_SECTIONS[0]) as TemplateSection,
      groupChannelTemplatePermissions((channelTemplate || TEMPLATE_SECTIONS[3]) as TemplateSection),
      (applicationTemplate || TEMPLATE_SECTIONS[1]) as TemplateSection,
      (knowledgeLibraryTemplate || TEMPLATE_SECTIONS[2]) as TemplateSection,
    ]
    if (toolTemplate) sections.push(toolTemplate as TemplateSection)
    return sections.map(filterHiddenTemplatePermissions)
  }, [applicationTemplate, channelTemplate, knowledgeTemplate, knowledgeLibraryTemplate, toolTemplate])

  const defaultPermissionIdsForRelation = (relation: ModelRelation): string[] => {
    return templateSections.flatMap((section) =>
      section.columns.flatMap((column) =>
        column.items
          .filter((item) => MODEL_LEVEL[relation] >= (RELATION_LEVEL[item.relation] ?? 99))
          .map((item) => item.id),
      ),
    )
  }

  const backendRelations = useMemo(() => {
    const rels = new Set<string>()
    ;(types || []).forEach((x) => x.relations.forEach((r) => rels.add(r)))
    return rels
  }, [types])

  const currentModel = useMemo(
    () => relationModels.find((m) => m.id === modelId) || null,
    [relationModels, modelId],
  )
  const normalizedNewModelName = useMemo(() => normalizeRelationModelName(newModelName), [newModelName])
  const createNameExists = useMemo(
    () => relationModelNameExists(relationModels, newModelName),
    [relationModels, newModelName],
  )

  useEffect(() => {
    if (!currentModel) return
    const permissions = currentModel.permissions || []
    if (currentModel.permissions_explicit !== false) {
      setSelectedPermissionIds(filterHiddenPermissionIds(permissions))
      return
    }
    const ids = templateSections.flatMap((section) =>
      section.columns.flatMap((column) =>
        column.items
          .filter((item) => MODEL_LEVEL[currentModel.relation] >= (RELATION_LEVEL[item.relation] ?? 99))
          .map((item) => item.id)
      )
    )
    setSelectedPermissionIds(ids)
  }, [currentModel, templateSections])

  const togglePermission = (permissionId: string, checked: boolean) => {
    setSelectedPermissionIds((prev) => {
      const next = new Set(prev)
      if (checked) {
        next.add(permissionId)
        const implies = MANAGE_PERMISSION_IMPLIES[permissionId]
        if (implies) implies.forEach((id) => next.add(id))
      } else {
        next.delete(permissionId)
        Object.entries(MANAGE_PERMISSION_IMPLIES).forEach(([parent, children]) => {
          if (children.includes(permissionId)) next.delete(parent)
        })
      }
      return Array.from(next)
    })
  }

  const refreshRelationModels = async () => {
    const res = await captureAndAlertRequestErrorHoc(getRelationModelsApi(), () => true)
    if (res === false) {
      setRelationModels(DEFAULT_RELATION_MODELS)
      setModelId("owner")
      return
    }
    if (!res) return
    setRelationModels(res)
    if (res.length > 0 && !res.some((m) => m.id === modelId)) setModelId(res[0].id)
  }

  const handleCreateModel = async () => {
    if (!normalizedNewModelName || createNameExists) return
    const res = await captureAndAlertRequestErrorHoc(
      createRelationModelApi({
        name: normalizedNewModelName,
        relation: newCreateRelation,
        permissions: defaultPermissionIdsForRelation(newCreateRelation),
      }),
    )
    if (res === false) {
      message({ variant: "error", description: t("system.relationModelCreateFailed") })
      return
    }
    await refreshRelationModels()
    message({ variant: "success", description: t("saved") })
    setCreateOpen(false)
    setNewModelName("")
  }

  const handleUpdateModel = async () => {
    if (!currentModel) return
    const res = await captureAndAlertRequestErrorHoc(
      updateRelationModelApi(currentModel.id, {
        name: currentModel.name,
        permissions: selectedPermissionIds,
      }),
    )
    if (res === false) return
    message({ variant: "success", description: t("saved") })
    await refreshRelationModels()
  }

  const handleResetSystemModel = async () => {
    if (!currentModel?.is_system) return
    const rel = currentModel.relation as ModelRelation
    const defaults = defaultPermissionIdsForRelation(rel)
    setSelectedPermissionIds(defaults)
    const res = await captureAndAlertRequestErrorHoc(
      updateRelationModelApi(currentModel.id, {
        name: currentModel.name,
        permissions: defaults,
      }),
    )
    if (res === false) {
      message({ variant: "error", description: t("system.relationModelSaveFailed") })
      await refreshRelationModels()
      return
    }
    message({ variant: "success", description: t("system.relationModelResetSuccess") })
    await refreshRelationModels()
  }

  const handleDeleteModel = async () => {
    if (!currentModel || currentModel.is_system) return
    const res = await captureAndAlertRequestErrorHoc(deleteRelationModelApi(currentModel.id))
    if (res === false) return
    message({ variant: "success", description: t("deleteSuccess") })
    await refreshRelationModels()
  }

  return (
    <>
    {isSuperAdmin ? (
    <Tabs defaultValue="roles" className="flex h-full min-h-0 w-full flex-col">
      <TabsList className="mb-2 shrink-0 self-start">
        <TabsTrigger value="roles">{t("system.roleManagement")}</TabsTrigger>
        <TabsTrigger value="rebac">{t("system.rebacSchemaTab")}</TabsTrigger>
      </TabsList>
      <TabsContent value="roles" className="mt-0 min-h-0 flex-1 overflow-hidden">
        <Roles />
      </TabsContent>
      <TabsContent value="rebac" className="mt-0 min-h-0 flex-1 overflow-hidden">
        <div className="flex h-full min-h-0 flex-col pb-2 pt-2" data-permission-surface="relation-model-editor">
          {types === null ? (
            <p className="text-sm text-muted-foreground">…</p>
          ) : types.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("build.empty")}</p>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col gap-4">
              <Button size="sm" className="h-8 self-start px-3" onClick={() => setCreateOpen(true)}>
                {t("system.relationModelCreateButton")}
              </Button>
              <div className="shrink-0 space-y-2">
                <div className="space-y-1">
                  <p className="text-sm">{t("system.relationModelSelectTemplate")}</p>
                  <p className="text-xs text-muted-foreground">{t("system.relationModelSelectTemplateHint")}</p>
                </div>
                <Select value={modelId} onValueChange={setModelId}>
                  <SelectTrigger className="w-[280px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {relationModels.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.is_system ? t(RELATION_LEVEL_I18N_KEY[item.relation]) : item.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="min-h-0 flex-1 space-y-4 overflow-y-auto pr-1">
                {templateSections.map((section) => (
                  <div key={section.title} className="rounded-md border p-3">
                    <p className="mb-2 text-base font-medium">{templateSectionTitle(section.title, t)}</p>
                    <div className={`grid gap-4 ${section.columns.length === 3 ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
                      {section.columns.map((col, idx) => (
                        <div key={`${section.title}-${idx}`} className="space-y-2">
                          {col.title ? (
                            <p className="text-sm font-medium text-muted-foreground">
                              {templateColumnTitle(col.title, t)}
                            </p>
                          ) : null}
                          {col.items.map((item) => {
                            const backendDefined = backendRelations.has(item.relation)
                            return (
                              <label key={item.id} className="flex items-start gap-2 text-sm">
                                <Checkbox
                                  checked={selectedPermissionIds.includes(item.id)}
                                  onCheckedChange={(checked) => togglePermission(item.id, Boolean(checked))}
                                />
                                <span className="leading-5">
                                  {templatePermissionLabel(item, t)}
                                  {!backendDefined ? (
                                    <span className="ml-1 text-xs text-orange-500">
                                      {t("system.relationModelBackendUndefined")}
                                    </span>
                                  ) : null}
                                </span>
                              </label>
                            )
                          })}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              <div className="flex shrink-0 items-center gap-2">
                <Button
                  size="sm"
                  onClick={handleUpdateModel}
                >
                  {t("system.relationModelUpdateButton")}
                </Button>
                {currentModel?.is_system ? (
                  <Button size="sm" variant="outline" onClick={handleResetSystemModel}>
                    {t("system.relationModelResetButton")}
                  </Button>
                ) : null}
                {!currentModel?.is_system && (
                  <Button size="sm" variant="outline" onClick={handleDeleteModel}>
                    {t("system.relationModelDeleteButton")}
                  </Button>
                )}
                <span className="text-xs text-muted-foreground">
                  {t("system.relationModelFooterHint")}
                </span>
              </div>

            </div>
          )}
        </div>
      </TabsContent>
    </Tabs>
    ) : (
    <div className="h-full w-full min-h-0">
      <Roles />
    </div>
    )}
    <Dialog
      open={createOpen}
      onOpenChange={(open) => {
        setCreateOpen(open)
        if (!open) setNewModelName("")
        else setNewCreateRelation("viewer")
      }}
    >
      <DialogContent className="sm:max-w-[480px]">
        <DialogHeader>
          <DialogTitle>{t("system.relationModelDialogTitle")}</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("system.relationModelNameLabel")}</p>
            <Input
              value={newModelName}
              onChange={(e) => setNewModelName(e.target.value)}
              placeholder={t("system.relationModelNamePlaceholder")}
            />
            {createNameExists ? (
              <p className="text-xs text-destructive">{t("system.relationModelNameExists")}</p>
            ) : null}
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("system.relationModelAuthLevelTitle")}</p>
            <Select
              value={newCreateRelation}
              onValueChange={(v) => setNewCreateRelation(v as ModelRelation)}
            >
              <SelectTrigger className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="owner">{t(RELATION_LEVEL_I18N_KEY.owner)}</SelectItem>
                <SelectItem value="manager">{t(RELATION_LEVEL_I18N_KEY.manager)}</SelectItem>
                <SelectItem value="editor">{t(RELATION_LEVEL_I18N_KEY.editor)}</SelectItem>
                <SelectItem value="viewer">{t(RELATION_LEVEL_I18N_KEY.viewer)}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setCreateOpen(false)}>{t("cancel")}</Button>
          <Button onClick={handleCreateModel} disabled={!normalizedNewModelName || createNameExists}>{t("confirmButton")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  )
}
