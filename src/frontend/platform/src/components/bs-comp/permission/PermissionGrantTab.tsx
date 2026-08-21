// @ts-strict-ignore
import { Button } from "@/components/bs-ui/button"
import { Checkbox } from "@/components/bs-ui/checkBox"
import {
  getGrantablePermissionModelsApi,
  mutateResourceGrantsApi,
  type GrantablePermissionModel,
  type MutateResourceGrantsResult,
  type PermissionGrantAssignee,
  type PermissionGrantMutationChange,
  type ResourcePermissionContext,
} from "@/controllers/API/permission"
import { LockKeyhole } from "lucide-react"
import { useEffect, useMemo, useState } from "react"
import { useTranslation } from "react-i18next"
import { SourceBadge } from "./SourceBadge"
import { SubjectSearchDepartment } from "./SubjectSearchDepartment"
import { SubjectSearchUser } from "./SubjectSearchUser"
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup"
import type {
  ResourceType,
  SelectedSubject,
  SubjectType,
} from "./types"

const SUBJECT_TYPES: SubjectType[] = ["user", "department", "user_group"]

interface PermissionGrantTabProps {
  resourceType: ResourceType
  resourceId: string
  context: ResourcePermissionContext
  assignees?: PermissionGrantAssignee[]
  fixedSubjectType?: SubjectType
  includeChildren?: boolean
  onIncludeChildrenChange?: (value: boolean) => void
  hideDepartmentIncludeChildrenControl?: boolean
  legacyAddLayout?: boolean
  showExistingAssignees?: boolean
  onSuccess: (result: MutateResourceGrantsResult) => void
}

function createMutationIdempotencyKey(): string {
  return `grant-mutate-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 10)}`
}

interface ExistingAssigneeRowProps {
  assignee: PermissionGrantAssignee
  context: ResourcePermissionContext
  models: GrantablePermissionModel[]
  pending: boolean
  onMove: (assignee: PermissionGrantAssignee, targetModelKey: string) => void
  onRemove: (assignee: PermissionGrantAssignee) => void
}

function ExistingAssigneeRow({
  assignee,
  context,
  models,
  pending,
  onMove,
  onRemove,
}: ExistingAssigneeRowProps) {
  const { t } = useTranslation("permission")
  const [targetModelKey, setTargetModelKey] = useState(assignee.model.key)
  const editable =
    context.mode === "CUSTOM" &&
    context.can_manage_permission &&
    assignee.scope === "LOCAL" &&
    assignee.editable &&
    !assignee.protected
  const currentIsGrantable = models.some(
    (model) => model.key === assignee.model.key,
  )

  useEffect(() => {
    setTargetModelKey(assignee.model.key)
  }, [assignee.assignee_id, assignee.model.key, assignee.assignee_version])

  return (
    <article className="grid gap-3 rounded-xl border p-3 md:grid-cols-[minmax(0,1fr)_minmax(11rem,0.7fr)_auto]">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-foreground">
            {assignee.subject.name ||
              `${assignee.subject.type}:${assignee.subject.id}`}
          </p>
          {assignee.protected && (
            <LockKeyhole
              aria-label={t("roster.protected")}
              className="size-4 shrink-0 text-amber-700"
            />
          )}
        </div>
        <div className="mt-1 flex flex-wrap gap-1">
          <SourceBadge source={assignee.source} />
          {assignee.scope === "INHERITED" && (
            <span className="rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
              {t("scope.inherited")}
            </span>
          )}
        </div>
      </div>

      <select
        aria-label={`grant.model.${assignee.assignee_id}`}
        value={targetModelKey}
        disabled={!editable || pending}
        onChange={(event) => setTargetModelKey(event.target.value)}
        className="min-h-11 rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
      >
        {!currentIsGrantable && (
          <option value={assignee.model.key}>{assignee.model.name}</option>
        )}
        {models.map((model) => (
          <option key={model.key} value={model.key}>
            {model.name}
          </option>
        ))}
      </select>

      <div className="flex flex-wrap items-start gap-2">
        <Button
          type="button"
          variant="outline"
          className="min-h-11"
          aria-label={`grant.move.${assignee.assignee_id}`}
          disabled={
            !editable || pending || targetModelKey === assignee.model.key
          }
          onClick={() => onMove(assignee, targetModelKey)}
        >
          {t("grant.move")}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="min-h-11 text-red-700"
          aria-label={`grant.remove.${assignee.assignee_id}`}
          disabled={!editable || pending}
          onClick={() => onRemove(assignee)}
        >
          {t("grant.remove")}
        </Button>
      </div>
    </article>
  )
}

export function PermissionGrantTab({
  resourceType,
  resourceId,
  context,
  assignees = [],
  fixedSubjectType,
  includeChildren: includeChildrenProp,
  onIncludeChildrenChange,
  hideDepartmentIncludeChildrenControl = false,
  legacyAddLayout = false,
  showExistingAssignees = true,
  onSuccess,
}: PermissionGrantTabProps) {
  const { t } = useTranslation("permission")
  const [models, setModels] = useState<GrantablePermissionModel[]>([])
  const [subjectType, setSubjectType] = useState<SubjectType>(
    fixedSubjectType ?? "user",
  )
  const [selectedSubjects, setSelectedSubjects] = useState<SelectedSubject[]>(
    [],
  )
  const [selectedModelKey, setSelectedModelKey] = useState("")
  const [internalIncludeChildren, setInternalIncludeChildren] = useState(false)
  const [loadingModels, setLoadingModels] = useState(false)
  const [pendingKey, setPendingKey] = useState<string | null>(null)
  const [conflict, setConflict] = useState(false)
  const includeChildren = includeChildrenProp ?? internalIncludeChildren
  const handleIncludeChildrenChange =
    onIncludeChildrenChange ?? setInternalIncludeChildren

  useEffect(() => {
    let cancelled = false
    setLoadingModels(true)
    setConflict(false)
    void getGrantablePermissionModelsApi(resourceType, resourceId)
      .then((result) => {
        if (cancelled) return
        const activeModels = result.filter((model) => model.active)
        setModels(activeModels)
        setSelectedModelKey((current) =>
          activeModels.some((model) => model.key === current)
            ? current
            : (activeModels[0]?.key ?? ""),
        )
      })
      .catch(() => {
        if (!cancelled) setConflict(true)
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false)
      })
    return () => {
      cancelled = true
    }
  }, [resourceId, resourceType])

  useEffect(() => {
    if (fixedSubjectType) setSubjectType(fixedSubjectType)
    setSelectedSubjects([])
  }, [fixedSubjectType, resourceId])

  const canEdit =
    context.mode === "CUSTOM" && context.can_manage_permission
  // Anyone already holding a grant here is checked and locked, whichever model
  // it is. Granting them again under a second model produced a duplicate row in
  // the roster — two permissions for one person, of which only the higher one
  // means anything. Changing someone's model is the roster's job, not this
  // panel's.
  const disabledSubjectIds = useMemo(
    () =>
      assignees
        .filter(
          (assignee) =>
            assignee.subject.type === subjectType && assignee.scope === "LOCAL",
        )
        .map((assignee) => Number(assignee.subject.id))
        .filter(Number.isFinite),
    [assignees, subjectType],
  )

  const mutate = async (
    operationKey: string,
    changes: PermissionGrantMutationChange[],
  ) => {
    if (!canEdit || pendingKey) return
    setPendingKey(operationKey)
    setConflict(false)
    try {
      const result = await mutateResourceGrantsApi(resourceType, resourceId, {
        idempotency_key: createMutationIdempotencyKey(),
        expected_resource_version: context.resource_version,
        expected_catalog_release_id: context.catalog_release_id,
        changes,
      })
      setSelectedSubjects([])
      onSuccess(result)
    } catch {
      setConflict(true)
    } finally {
      setPendingKey(null)
    }
  }

  const handleAdd = () => {
    if (!selectedModelKey || selectedSubjects.length === 0) return
    void mutate(
      "add",
      selectedSubjects.map((subject) => ({
        op: "ADD",
        model_key: selectedModelKey,
        subject: {
          type: subject.type,
          id: String(subject.id),
          ...(subject.type === "department"
            ? {
                include_children: includeChildren,
                userset_relation: includeChildren
                  ? "subtree_member"
                  : "member",
              }
            : {}),
        },
      })),
    )
  }

  const handleMove = (
    assignee: PermissionGrantAssignee,
    targetModelKey: string,
  ) => {
    void mutate(`move-${assignee.assignee_id}`, [
      {
        op: "MOVE",
        assignee_id: assignee.assignee_id,
        expected_assignee_version: assignee.assignee_version,
        target_model_key: targetModelKey,
      },
    ])
  }

  const handleRemove = (assignee: PermissionGrantAssignee) => {
    void mutate(`remove-${assignee.assignee_id}`, [
      {
        op: "REMOVE",
        assignee_id: assignee.assignee_id,
        expected_assignee_version: assignee.assignee_version,
      },
    ])
  }

  const subjectLabel = t(
    `subject.${subjectType === "user_group" ? "userGroup" : subjectType}`,
  )
  const selectedSummaryText = selectedSubjects
    .map((subject) => subject.name)
    .join("、")
  const subjectPicker = (
    <>
      {subjectType === "user" && (
        <SubjectSearchUser
          value={selectedSubjects}
          onChange={setSelectedSubjects}
          resourceType={resourceType}
          resourceId={resourceId}
          disabledIds={disabledSubjectIds}
        />
      )}
      {subjectType === "department" && (
        <SubjectSearchDepartment
          value={selectedSubjects}
          onChange={setSelectedSubjects}
          resourceType={resourceType}
          resourceId={resourceId}
          includeChildren={includeChildren}
          onIncludeChildrenChange={handleIncludeChildrenChange}
          disabledIds={disabledSubjectIds}
          showIncludeChildrenToggle={false}
        />
      )}
      {subjectType === "user_group" && (
        <SubjectSearchUserGroup
          value={selectedSubjects}
          onChange={setSelectedSubjects}
          resourceType={resourceType}
          resourceId={resourceId}
          disabledIds={disabledSubjectIds}
        />
      )}
    </>
  )

  if (legacyAddLayout) {
    return (
      <div
        className="flex h-full min-h-0 flex-col overflow-hidden"
        data-testid="legacy-permission-grant-layout"
      >
        {conflict && (
          <p
            className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-900"
            role="alert"
          >
            {t("grant.conflict")}
          </p>
        )}

        <div className="min-h-0 flex-1 overflow-hidden">
          {subjectPicker}
        </div>

        {subjectType === "department" &&
          !hideDepartmentIncludeChildrenControl && (
            <label className="mt-3 flex h-10 shrink-0 items-center gap-2 text-sm">
              <Checkbox
                checked={includeChildren}
                onCheckedChange={(checked) =>
                  handleIncludeChildrenChange(checked === true)
                }
              />
              {t("source.includeChildren")}
            </label>
          )}

        <div className="mt-4 flex h-10 shrink-0 items-center gap-4 overflow-hidden">
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
            <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
              {`${t("action.grant")}${subjectLabel}:`}
            </span>
            <span className="truncate text-[14px] leading-[22px] text-[#4E5969]">
              {selectedSummaryText}
            </span>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <span className="shrink-0 text-[14px] font-normal leading-[22px] text-[#999999]">
              {t("action.grant")}
            </span>
            <select
              aria-label={t("grant.addModel")}
              value={selectedModelKey}
              disabled={loadingModels || models.length === 0}
              onChange={(event) => setSelectedModelKey(event.target.value)}
              className="h-8 w-[132px] rounded-[6px] border-0 bg-white px-1 text-[14px] leading-[22px] text-[#212121] outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
            >
              {models.map((model) => (
                <option key={model.key} value={model.key}>
                  {model.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-4 flex shrink-0 justify-end border-t pt-4">
          <Button
            type="button"
            disabled={
              pendingKey !== null ||
              selectedSubjects.length === 0 ||
              !selectedModelKey
            }
            onClick={handleAdd}
          >
            {t("grant.submit")}
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-col gap-4">
      {!canEdit && (
        <p className="rounded-lg border bg-muted/30 p-3 text-sm text-muted-foreground">
          {t("grant.readOnly")}
        </p>
      )}
      {conflict && (
        <p
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm font-medium text-red-900"
          role="alert"
        >
          {t("grant.conflict")}
        </p>
      )}

      {showExistingAssignees && assignees.length > 0 && (
        <section aria-label={t("grant.existing")} className="space-y-2">
          <h3 className="text-sm font-semibold text-foreground">
            {t("grant.existing")}
          </h3>
          {assignees.map((assignee) => (
            <ExistingAssigneeRow
              key={assignee.assignee_id}
              assignee={assignee}
              context={context}
              models={models}
              pending={pendingKey !== null}
              onMove={handleMove}
              onRemove={handleRemove}
            />
          ))}
        </section>
      )}

      {canEdit && (
        <section
          aria-label={t("grant.add")}
          className="flex min-h-0 flex-col gap-3 rounded-xl border p-4"
        >
          {!fixedSubjectType && (
            <div className="flex flex-wrap gap-1 rounded-lg bg-muted p-1">
              {SUBJECT_TYPES.map((type) => (
                <button
                  key={type}
                  type="button"
                  aria-pressed={subjectType === type}
                  className="min-h-11 rounded-md px-3 text-sm text-muted-foreground aria-pressed:bg-background aria-pressed:text-foreground aria-pressed:shadow-sm"
                  onClick={() => {
                    setSubjectType(type)
                    setSelectedSubjects([])
                  }}
                >
                  {t(`subject.${type === "user_group" ? "userGroup" : type}`)}
                </button>
              ))}
            </div>
          )}

          <div className="min-h-48">
            {subjectPicker}
          </div>

          {subjectType === "department" && (
            <label className="flex min-h-11 items-center gap-2 text-sm">
              <Checkbox
                checked={includeChildren}
                onCheckedChange={(checked) =>
                  handleIncludeChildrenChange(checked === true)
                }
              />
              {t("source.includeChildren")}
            </label>
          )}

          <div className="flex flex-wrap items-end justify-between gap-3 border-t pt-3">
            <label className="min-w-56 flex-1 text-sm font-medium">
              <span className="mb-1 block">{t("grant.model")}</span>
              <select
                aria-label={t("grant.addModel")}
                value={selectedModelKey}
                disabled={loadingModels || models.length === 0}
                onChange={(event) => setSelectedModelKey(event.target.value)}
                className="min-h-11 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {models.map((model) => (
                  <option key={model.key} value={model.key}>
                    {model.name}
                  </option>
                ))}
              </select>
            </label>
            <Button
              type="button"
              className="min-h-11"
              disabled={
                pendingKey !== null ||
                selectedSubjects.length === 0 ||
                !selectedModelKey
              }
              onClick={handleAdd}
            >
              {t("grant.submit")}
            </Button>
          </div>
        </section>
      )}
    </div>
  )
}
