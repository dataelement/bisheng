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

const RELATION_LEVEL: Record<string, number> = {
  can_read: 1,
  can_edit: 2,
  can_manage: 3,
  can_delete: 4,
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

const DEFAULT_RELATION_MODELS: RelationModel[] = [
  { id: "owner", name: "所有者", relation: "owner", grant_tier: "owner", permissions: [], permissions_explicit: false, is_system: true },
  { id: "manager", name: "可管理", relation: "manager", grant_tier: "manager", permissions: [], permissions_explicit: false, is_system: true },
  { id: "editor", name: "可编辑", relation: "editor", grant_tier: "usage", permissions: [], permissions_explicit: false, is_system: true },
  { id: "viewer", name: "可查看", relation: "viewer", grant_tier: "usage", permissions: [], permissions_explicit: false, is_system: true },
]

const TEMPLATE_SECTIONS: TemplateSection[] = [
  {
    title: "知识空间模块",
    columns: [
      {
        title: "空间级",
        items: [
          { id: "view_space", label: "查看空间", relation: "can_read" },
          { id: "edit_space", label: "编辑空间信息", relation: "can_edit" },
          { id: "delete_space", label: "删除空间", relation: "can_delete" },
          { id: "share_space", label: "分享空间", relation: "can_manage" },
          { id: "manage_space_relation", label: "管理空间协作者", relation: "can_manage" },
        ],
      },
      {
        title: "文件夹级",
        items: [
          { id: "view_folder", label: "查看文件夹", relation: "can_read" },
          { id: "create_folder", label: "创建文件夹", relation: "can_edit" },
          { id: "rename_folder", label: "重命名文件夹", relation: "can_edit" },
          { id: "delete_folder", label: "删除文件夹", relation: "can_delete" },
          { id: "download_folder", label: "下载文件夹", relation: "can_read" },
          { id: "manage_folder_relation", label: "管理文件夹协作者", relation: "can_manage" },
        ],
      },
      {
        title: "文件级",
        items: [
          { id: "view_file", label: "查看文件", relation: "can_read" },
          { id: "upload_file", label: "上传文件", relation: "can_edit" },
          { id: "rename_file", label: "重命名文件", relation: "can_edit" },
          { id: "delete_file", label: "删除文件", relation: "can_delete" },
          { id: "download_file", label: "下载文件", relation: "can_read" },
          { id: "share_file", label: "分享文件", relation: "can_manage" },
          { id: "manage_file_relation", label: "管理文件协作者", relation: "can_manage" },
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
          { id: "view_app", label: "查看应用", relation: "can_read" },
          { id: "use_app", label: "使用应用", relation: "can_read" },
          { id: "edit_app", label: "编辑应用", relation: "can_edit" },
          { id: "delete_app", label: "删除应用", relation: "can_delete" },
        ],
      },
      {
        title: "",
        items: [
          { id: "publish_app", label: "发布应用", relation: "can_manage" },
          { id: "unpublish_app", label: "下线应用", relation: "can_manage" },
          { id: "share_app", label: "分享应用", relation: "can_manage" },
        ],
      },
      {
        title: "",
        items: [
          { id: "manage_app_owner", label: "管理应用所有者", relation: "can_manage" },
          { id: "manage_app_manager", label: "管理应用管理者", relation: "can_manage" },
          { id: "manage_app_viewer", label: "管理应用使用者", relation: "can_manage" },
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
          { id: "view_kb", label: "查看知识库", relation: "can_read" },
          { id: "use_kb", label: "使用知识库", relation: "can_read" },
          { id: "edit_kb", label: "编辑知识库", relation: "can_edit" },
          { id: "delete_kb", label: "删除知识库", relation: "can_delete" },
        ],
      },
      {
        title: "",
        items: [
          { id: "manage_kb_owner", label: "管理知识库所有者", relation: "can_manage" },
          { id: "manage_kb_manager", label: "管理知识库管理者", relation: "can_manage" },
          { id: "manage_kb_viewer", label: "管理知识库使用者", relation: "can_manage" },
        ],
      },
    ],
  },
]

export default function RolesAndPermissions() {
  const { t } = useTranslation()
  const { user } = useContext(userContext)
  const [types, setTypes] = useState<RebacSchemaType[] | null>(null)
  const [applicationTemplate, setApplicationTemplate] = useState<PermissionTemplateSection | null>(null)
  const [knowledgeTemplate, setKnowledgeTemplate] = useState<PermissionTemplateSection | null>(null)
  const [knowledgeLibraryTemplate, setKnowledgeLibraryTemplate] = useState<PermissionTemplateSection | null>(null)
  const [toolTemplate, setToolTemplate] = useState<PermissionTemplateSection | null>(null)
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
  }, [user?.role])

  const templateSections = useMemo<TemplateSection[]>(() => {
    const sections = [...TEMPLATE_SECTIONS]
    if (knowledgeTemplate) {
      sections[0] = knowledgeTemplate as TemplateSection
    }
    if (applicationTemplate) {
      sections[1] = applicationTemplate as TemplateSection
    }
    if (knowledgeLibraryTemplate) {
      sections[2] = knowledgeLibraryTemplate as TemplateSection
    }
    if (toolTemplate) {
      sections.splice(3, 0, toolTemplate as TemplateSection)
    }
    return sections
  }, [applicationTemplate, knowledgeTemplate, knowledgeLibraryTemplate, toolTemplate])

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

  useEffect(() => {
    if (!currentModel) return
    const permissions = currentModel.permissions || []
    if (currentModel.permissions_explicit !== false) {
      setSelectedPermissionIds(permissions)
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
      if (checked) return Array.from(new Set([...prev, permissionId]))
      return prev.filter((id) => id !== permissionId)
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
    if (!newModelName.trim()) return
    const res = await captureAndAlertRequestErrorHoc(
      createRelationModelApi({
        name: newModelName.trim(),
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
        <div className="pb-6 pt-2">
          {user?.role !== "admin" ? (
            <p className="text-sm text-muted-foreground">{t("system.rebacAdminOnly")}</p>
          ) : types === null ? (
            <p className="text-sm text-muted-foreground">…</p>
          ) : types.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("build.empty")}</p>
          ) : (
            <div className="space-y-4">
              <Button size="sm" className="h-8 px-3" onClick={() => setCreateOpen(true)}>
                {t("system.relationModelCreateButton")}
              </Button>
              <div className="space-y-2">
                <p className="text-sm">{t("system.relationModelSelectTemplate")}</p>
                <Select value={modelId} onValueChange={setModelId}>
                  <SelectTrigger className="w-[280px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {relationModels.map((item) => (
                      <SelectItem key={item.id} value={item.id}>
                        {item.is_system
                          ? t(RELATION_LEVEL_I18N_KEY[item.relation])
                          : `${item.name}（${t(RELATION_LEVEL_I18N_KEY[item.relation])}）`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {templateSections.map((section) => (
                <div key={section.title} className="rounded-md border p-3">
                  <p className="mb-2 text-base font-medium">{section.title}</p>
                  <div className={`grid gap-4 ${section.columns.length === 3 ? "md:grid-cols-3" : "md:grid-cols-2"}`}>
                    {section.columns.map((col, idx) => (
                      <div key={`${section.title}-${idx}`} className="space-y-2">
                        {col.title ? <p className="text-sm font-medium text-muted-foreground">{col.title}</p> : null}
                        {col.items.map((item) => {
                          const backendDefined = backendRelations.has(item.relation)
                          return (
                            <label key={item.id} className="flex items-start gap-2 text-sm">
                              <Checkbox
                                checked={selectedPermissionIds.includes(item.id)}
                                onCheckedChange={(checked) => togglePermission(item.id, Boolean(checked))}
                              />
                              <span className="leading-5">
                                {item.label}
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

              <div className="flex items-center gap-2">
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
          </div>
          <div className="space-y-2">
            <p className="text-sm font-medium">{t("system.relationModelAuthLevelTitle")}</p>
            <p className="text-xs text-muted-foreground">{t("system.relationModelAuthLevelHint")}</p>
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
          <Button onClick={handleCreateModel} disabled={!newModelName.trim()}>{t("confirmButton")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    </>
  )
}
