import { Loader2, LockKeyhole, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
  getGrantablePermissionModels,
  mutateResourceGrants,
} from "~/api/permission";
import type {
  GrantablePermissionModel,
  MutateResourceGrantsResult,
  PermissionGrantAssignee,
  PermissionGrantMutationChange,
  ResourcePermissionContext,
  ResourceType,
  SelectedSubject,
  SubjectType,
} from "~/api/permission";
import { Button, Checkbox } from "~/components/ui";
import { useLocalize } from "~/hooks";
import { SubjectSearchDepartment } from "./SubjectSearchDepartment";
import { SubjectSearchUser } from "./SubjectSearchUser";
import { SubjectSearchUserGroup } from "./SubjectSearchUserGroup";

const SUBJECT_TYPES: SubjectType[] = ["user", "department", "user_group"];

interface PermissionGrantTabProps {
  resourceType: ResourceType;
  resourceId: string;
  context: ResourcePermissionContext;
  assignees?: PermissionGrantAssignee[];
  fixedSubjectType?: SubjectType;
  includeChildren?: boolean;
  onIncludeChildrenChange?: (value: boolean) => void;
  hideDepartmentIncludeChildrenControl?: boolean;
  legacyAddLayout?: boolean;
  showExistingAssignees?: boolean;
  onSuccess: (result: MutateResourceGrantsResult) => void;
}

function createIdempotencyKey(): string {
  return `grant-mutation-${Date.now()}-${Math.random()
    .toString(36)
    .slice(2, 10)}`;
}

function isEditable(
  assignee: PermissionGrantAssignee,
  context: ResourcePermissionContext,
): boolean {
  return (
    context.mode === "CUSTOM" &&
    context.can_manage_permission &&
    assignee.scope === "LOCAL" &&
    assignee.editable &&
    !assignee.protected
  );
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
  const localize = useLocalize();
  const [models, setModels] = useState<GrantablePermissionModel[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [subjectType, setSubjectType] = useState<SubjectType>(
    fixedSubjectType ?? "user",
  );
  const [selectedSubjects, setSelectedSubjects] = useState<SelectedSubject[]>(
    [],
  );
  const [selectedModelKey, setSelectedModelKey] = useState("");
  const [internalIncludeChildren, setInternalIncludeChildren] = useState(false);
  const [targetModels, setTargetModels] = useState<Record<number, string>>({});
  const [removedIds, setRemovedIds] = useState<Set<number>>(new Set());
  const [queuedAdds, setQueuedAdds] = useState<
    PermissionGrantMutationChange[]
  >([]);
  const [submitting, setSubmitting] = useState(false);
  const [conflict, setConflict] = useState(false);
  const includeChildren = includeChildrenProp ?? internalIncludeChildren;
  const handleIncludeChildrenChange =
    onIncludeChildrenChange ?? setInternalIncludeChildren;

  useEffect(() => {
    let cancelled = false;
    setModelsLoading(true);
    setConflict(false);
    void getGrantablePermissionModels(resourceType, resourceId)
      .then((result) => {
        if (cancelled) return;
        const activeModels = result.filter((model) => model.active);
        setModels(activeModels);
        setSelectedModelKey((current) =>
          activeModels.some((model) => model.key === current)
            ? current
            : (activeModels[0]?.key ?? ""),
        );
      })
      .catch(() => {
        if (!cancelled) setConflict(true);
      })
      .finally(() => {
        if (!cancelled) setModelsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [resourceId, resourceType]);

  useEffect(() => {
    setTargetModels({});
    setRemovedIds(new Set());
    setQueuedAdds([]);
    setSelectedSubjects([]);
    setConflict(false);
  }, [context.resource_version, resourceId]);

  useEffect(() => {
    if (fixedSubjectType) setSubjectType(fixedSubjectType);
    setSelectedSubjects([]);
  }, [fixedSubjectType, resourceId]);

  const disabledSubjectIds = useMemo(
    () => [
      ...assignees
        .filter(
          (assignee) =>
            assignee.subject.type === subjectType &&
            assignee.model.key === selectedModelKey,
        )
        .map((assignee) => Number(assignee.subject.id))
        .filter(Number.isFinite),
      ...queuedAdds
        .filter(
          (change) =>
            change.op === "ADD" &&
            change.model_key === selectedModelKey &&
            change.subject.type === subjectType,
        )
        .map((change) =>
          change.op === "ADD" ? Number(change.subject.id) : Number.NaN,
        )
        .filter(Number.isFinite),
    ],
    [assignees, queuedAdds, selectedModelKey, subjectType],
  );

  const pendingChanges = useMemo<PermissionGrantMutationChange[]>(() => {
    const changes: PermissionGrantMutationChange[] = [];
    for (const assignee of assignees) {
      if (!isEditable(assignee, context)) continue;
      if (removedIds.has(assignee.assignee_id)) {
        changes.push({
          op: "REMOVE",
          assignee_id: assignee.assignee_id,
          expected_assignee_version: assignee.assignee_version,
        });
        continue;
      }
      const targetModel = targetModels[assignee.assignee_id];
      if (targetModel && targetModel !== assignee.model.key) {
        changes.push({
          op: "MOVE",
          assignee_id: assignee.assignee_id,
          expected_assignee_version: assignee.assignee_version,
          target_model_key: targetModel,
        });
      }
    }
    return [...changes, ...queuedAdds];
  }, [assignees, context, queuedAdds, removedIds, targetModels]);

  const selectedAddChanges = useMemo<PermissionGrantMutationChange[]>(
    () =>
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
    [includeChildren, selectedModelKey, selectedSubjects],
  );

  const handleAdd = () => {
    if (!selectedModelKey || selectedSubjects.length === 0) return;
    setQueuedAdds((current) => [...current, ...selectedAddChanges]);
    setSelectedSubjects([]);
  };

  const handleSubmit = async (
    changes: PermissionGrantMutationChange[] = pendingChanges,
  ) => {
    if (changes.length === 0 || submitting) return;
    setSubmitting(true);
    setConflict(false);
    try {
      const result = await mutateResourceGrants(resourceType, resourceId, {
        idempotency_key: createIdempotencyKey(),
        expected_resource_version: context.resource_version,
        expected_catalog_release_id: context.catalog_release_id,
        changes,
      });
      onSuccess(result);
      setTargetModels({});
      setRemovedIds(new Set());
      setQueuedAdds([]);
      setSelectedSubjects([]);
    } catch {
      setConflict(true);
    } finally {
      setSubmitting(false);
    }
  };

  const canEdit =
    context.mode === "CUSTOM" && context.can_manage_permission;

  const subjectLabel = localize(`f048_permission.subject.${subjectType}`);
  const selectedSummaryText = selectedSubjects
    .map((subject) => subject.name)
    .join("、");
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
          disabledIds={disabledSubjectIds}
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
  );

  if (legacyAddLayout) {
    return (
      <div
        className="flex h-full min-h-0 flex-col overflow-hidden"
        data-testid="legacy-permission-grant-layout"
      >
        {conflict && (
          <p
            className="mb-3 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
            role="alert"
          >
            {localize("f048_permission.grant.conflict")}
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
              {localize("f048_permission.source.include_children")}
            </label>
          )}

        <div className="mt-4 flex h-10 shrink-0 items-center gap-4 overflow-hidden">
          <div className="flex min-w-0 flex-1 items-center gap-2 overflow-hidden">
            <span className="shrink-0 text-sm font-normal leading-[22px] text-[#999999]">
              {`${localize("com_permission.selected_prefix")}${subjectLabel}:`}
            </span>
            <span className="truncate text-sm leading-[22px] text-[#4E5969]">
              {selectedSummaryText}
            </span>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <span className="shrink-0 text-sm font-normal leading-[22px] text-[#999999]">
              {localize("com_permission.uniform_grant")}
            </span>
            <select
              aria-label={localize("f048_permission.grant.add_model")}
              value={selectedModelKey}
              disabled={modelsLoading || models.length === 0}
              onChange={(event) => setSelectedModelKey(event.target.value)}
              className="h-8 w-[132px] rounded-md border-0 bg-white px-1 text-sm leading-[22px] text-[#212121] outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40 disabled:opacity-60"
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
              selectedAddChanges.length === 0 ||
              !selectedModelKey ||
              submitting
            }
            onClick={() => void handleSubmit(selectedAddChanges)}
          >
            {submitting && (
              <Loader2 aria-hidden="true" className="animate-spin" />
            )}
            {localize("f048_permission.grant.submit")}
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-col gap-4">
      {conflict && (
        <p
          className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          role="alert"
        >
          {localize("f048_permission.grant.conflict")}
        </p>
      )}

      {showExistingAssignees && (
        <section className="space-y-3">
          <h3 className="text-sm font-medium text-[#212121]">
            {localize("f048_permission.grant.existing")}
          </h3>
          {assignees.map((assignee) => {
            const editable = isEditable(assignee, context);
            const removed = removedIds.has(assignee.assignee_id);
            return (
              <div
                key={assignee.assignee_id}
                className="grid items-center gap-2 rounded-lg border border-[#EBECF0] p-3 sm:grid-cols-[minmax(0,1fr)_minmax(10rem,0.6fr)_auto]"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-[#212121]">
                    {assignee.subject.name ||
                      `${assignee.subject.type}:${assignee.subject.id}`}
                  </p>
                  <p className="mt-1 text-xs text-[#818181]">
                    {assignee.source.type}
                    {assignee.protected && (
                      <span className="ml-2 inline-flex items-center gap-1">
                        <LockKeyhole aria-hidden="true" className="size-3" />
                        {localize("f048_permission.roster.protected")}
                      </span>
                    )}
                  </p>
                </div>
                <select
                  aria-label={`${localize(
                    "f048_permission.grant.model",
                  )}.${assignee.assignee_id}`}
                  value={
                    targetModels[assignee.assignee_id] ?? assignee.model.key
                  }
                  disabled={!editable || removed || modelsLoading}
                  onChange={(event) =>
                    setTargetModels((current) => ({
                      ...current,
                      [assignee.assignee_id]: event.target.value,
                    }))
                  }
                  className="h-10 rounded-md border border-[#D9D9D9] bg-white px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
                >
                  {models.map((model) => (
                    <option key={model.key} value={model.key}>
                      {model.name}
                    </option>
                  ))}
                </select>
                <Button
                  type="button"
                  color="danger"
                  variant="text"
                  size="medium"
                  iconOnly
                  aria-label={`${localize(
                    "f048_permission.grant.remove",
                  )}.${assignee.assignee_id}`}
                  disabled={!editable}
                  onClick={() =>
                    setRemovedIds((current) => {
                      const next = new Set(current);
                      if (next.has(assignee.assignee_id)) {
                        next.delete(assignee.assignee_id);
                      } else {
                        next.add(assignee.assignee_id);
                      }
                      return next;
                    })
                  }
                >
                  <Trash2 aria-hidden="true" />
                </Button>
              </div>
            );
          })}
        </section>
      )}

      {canEdit && (
        <section className="space-y-3 rounded-lg border border-[#EBECF0] p-3">
          {!fixedSubjectType && (
            <div className="flex flex-wrap gap-1 rounded-md bg-black/[0.04] p-1">
              {SUBJECT_TYPES.map((type) => (
                <button
                  key={type}
                  type="button"
                  aria-pressed={subjectType === type}
                  className="min-h-10 rounded px-3 text-sm text-[#818181] aria-pressed:bg-white aria-pressed:text-blue-500"
                  onClick={() => {
                    setSubjectType(type);
                    setSelectedSubjects([]);
                  }}
                >
                  {localize(`f048_permission.subject.${type}`)}
                </button>
              ))}
            </div>
          )}

          <div className="min-h-40">
            {subjectPicker}
          </div>

          {subjectType === "department" && (
            <label className="flex min-h-10 items-center gap-2 text-sm">
              <Checkbox
                checked={includeChildren}
                onCheckedChange={(checked) =>
                  handleIncludeChildrenChange(checked === true)
                }
              />
              {localize("f048_permission.source.include_children")}
            </label>
          )}

          <div className="flex flex-wrap items-end gap-2">
            <label className="min-w-52 flex-1 text-sm">
              <span className="mb-1 block">
                {localize("f048_permission.grant.add_model")}
              </span>
              <select
                aria-label={localize("f048_permission.grant.add_model")}
                value={selectedModelKey}
                disabled={modelsLoading || models.length === 0}
                onChange={(event) => setSelectedModelKey(event.target.value)}
                className="h-10 w-full rounded-md border border-[#D9D9D9] bg-white px-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
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
              color="default"
              variant="outlined"
              size="large"
              disabled={
                selectedSubjects.length === 0 || !selectedModelKey
              }
              onClick={handleAdd}
            >
              <Plus aria-hidden="true" />
              {localize("f048_permission.grant.add")}
            </Button>
          </div>
        </section>
      )}

      <div className="flex items-center justify-between gap-3 border-t pt-3">
        <p className="text-xs text-[#818181]">
          {localize("f048_permission.grant.pending", {
            count: pendingChanges.length,
          })}
        </p>
        <Button
          type="button"
          disabled={pendingChanges.length === 0 || submitting}
          onClick={() => void handleSubmit()}
        >
          {submitting && (
            <Loader2 aria-hidden="true" className="animate-spin" />
          )}
          {localize("f048_permission.grant.submit")}
        </Button>
      </div>
    </div>
  );
}
