import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  createSpaceApi,
  getKnowledgeSpaceAutoTagVisibilityApi,
  getKnowledgeSpaceTagLibrariesApi,
  getKnowledgeSpaceTagLibraryDetailApi,
  getSpaceInfoApi,
  updateSpaceApi,
  VisibilityType,
} from "~/api/knowledge";
import type {
  KnowledgeSpace,
  KnowledgeSpaceTagLibraryListItem,
} from "~/api/knowledge";
import {
  getCreationPermissionContext,
  getGrantablePermissionModels,
  getResourcePermissionContext,
  getResourcePermissionGrants,
  mutateResourceGrants,
} from "~/api/permission";
import type { GrantablePermissionModel } from "~/api/permission";
import { usePermissionDraft } from "~/components/permission/usePermissionDraft";
import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";

const MAX_CUSTOM_TAGS = 200;

export type KnowledgeSpaceSettingsMode = "create" | "edit";

export interface KnowledgeSpaceSettingsFormState {
  name: string;
  description: string;
  visibility: VisibilityType;
  isReleased: boolean;
  autoTagEnabled: boolean;
  autoTagMode: "library" | "custom";
  autoTagLibraryId: number | null;
  autoTagCustomText: string;
}

const INITIAL_FORM: KnowledgeSpaceSettingsFormState = {
  name: "",
  description: "",
  visibility: VisibilityType.APPROVAL,
  isReleased: true,
  autoTagEnabled: false,
  autoTagMode: "library",
  autoTagLibraryId: null,
  autoTagCustomText: "",
};

function permissionEntryToDraftRow(
  entry: Awaited<ReturnType<typeof getResourcePermissionGrants>>["data"][number],
): PermissionDraftRow {
  return {
    subjectType: entry.subject.type,
    subjectId: Number(entry.subject.id),
    subjectName: entry.subject.name ?? "",
    modelKey: entry.model.key,
    modelName: entry.model.name,
    modelLevel: entry.model.level,
    includeChildren: entry.source.include_children,
    assigneeId: entry.assignee_id,
    assigneeVersion: entry.assignee_version,
    sourceType: entry.source.type,
    scope: entry.scope,
    inheritedFrom: entry.inherited_from,
    protected: entry.protected,
    editable: entry.editable,
  };
}

export function parseKnowledgeSpaceCustomTags(text: string): string[] {
  return Array.from(
    new Set(
      text
        .split(/\r?\n/)
        .map((tag) => tag.trim())
        .filter(Boolean),
    ),
  ).slice(0, MAX_CUSTOM_TAGS);
}

export function useKnowledgeSpaceSettingsForm(spaceId?: string) {
  const mode: KnowledgeSpaceSettingsMode = spaceId ? "edit" : "create";
  const queryClient = useQueryClient();
  const permissionDraft = usePermissionDraft();
  const {
    rows: permissionRows,
    diff: permissionDiff,
    hasChanges: permissionHasChanges,
    addRows: addPermissionRows,
    replaceRows: replacePermissionRows,
    reset: resetPermissionDraft,
  } = permissionDraft;
  const [form, setForm] =
    useState<KnowledgeSpaceSettingsFormState>(INITIAL_FORM);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [canEdit, setCanEdit] = useState(mode === "create");
  const [canManagePermissions, setCanManagePermissions] = useState(false);
  const [relationModels, setRelationModels] = useState<GrantablePermissionModel[]>([]);
  const [catalogReleaseId, setCatalogReleaseId] = useState<number | null>(null);
  const [resourceVersion, setResourceVersion] = useState<number | null>(null);
  const creationRequestIdRef = useRef(crypto.randomUUID());
  const [createdSpace, setCreatedSpace] = useState<KnowledgeSpace | null>(null);
  const [permissionRetryStatus, setPermissionRetryStatus] = useState<
    "idle" | "retrying" | "success" | "failed"
  >("idle");
  const [autoTagFeatureVisible, setAutoTagFeatureVisible] = useState(false);
  const [tagLibraries, setTagLibraries] = useState<
    KnowledgeSpaceTagLibraryListItem[]
  >([]);
  const [autoTagPreview, setAutoTagPreview] = useState<string[]>([]);

  const updateForm = useCallback(
    <K extends keyof KnowledgeSpaceSettingsFormState>(
      key: K,
      value: KnowledgeSpaceSettingsFormState[K],
    ) => {
      setForm((current) => ({ ...current, [key]: value }));
    },
    [],
  );

  useEffect(() => {
    let cancelled = false;
    getKnowledgeSpaceAutoTagVisibilityApi()
      .then(async ({ visible }) => {
        if (cancelled) return;
        setAutoTagFeatureVisible(visible);
        if (!visible) return;
        const libraries = await getKnowledgeSpaceTagLibrariesApi({
          page: 1,
          page_size: 200,
        });
        if (cancelled) return;
        setTagLibraries(libraries.data);
        if (mode === "create" && libraries.data.length === 1) {
          updateForm("autoTagLibraryId", libraries.data[0].id);
        }
      })
      .catch(() => {
        if (!cancelled) setAutoTagFeatureVisible(false);
      });
    return () => {
      cancelled = true;
    };
  }, [mode, updateForm]);

  useEffect(() => {
    let cancelled = false;
    if (
      !autoTagFeatureVisible ||
      form.autoTagMode !== "library" ||
      !form.autoTagLibraryId
    ) {
      setAutoTagPreview([]);
      return () => {
        cancelled = true;
      };
    }
    getKnowledgeSpaceTagLibraryDetailApi(form.autoTagLibraryId)
      .then((library) => {
        if (!cancelled) setAutoTagPreview(library.tags);
      })
      .catch(() => {
        if (!cancelled) setAutoTagPreview([]);
      });
    return () => {
      cancelled = true;
    };
  }, [autoTagFeatureVisible, form.autoTagLibraryId, form.autoTagMode]);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);

    const load = async () => {
      if (mode === "create") {
        try {
          const context = await getCreationPermissionContext("knowledge_space");
          if (!cancelled) {
            setRelationModels(context.grantable_models);
            setCatalogReleaseId(context.catalog_release_id);
            setCanManagePermissions(context.can_configure_initial_permissions);
          }
        } catch {
          if (!cancelled) {
            setRelationModels([]);
            setCanManagePermissions(false);
          }
        } finally {
          if (!cancelled) setLoading(false);
        }
        return;
      }

      if (!spaceId) return;
      setLoading(true);
      try {
        const space = await getSpaceInfoApi(spaceId);
        if (cancelled) return;
        const canEditSpace = Boolean(space.actions?.includes("edit"));
        const canManageSpace = Boolean(space.actions?.includes("manage_permission"));
        if (!canEditSpace && !canManageSpace) {
          throw new Error("Knowledge space settings access denied");
        }
        setCanEdit(canEditSpace);
        setForm({
          name: space.name,
          description: space.description ?? "",
          visibility: space.visibility,
          isReleased: space.isReleased,
          autoTagEnabled: Boolean(space.autoTagEnabled),
          autoTagMode: space.autoTagMode ?? "library",
          autoTagLibraryId: space.autoTagLibraryId ?? null,
          autoTagCustomText: (space.autoTagCustomTags ?? []).join("\n"),
        });

        if (!canManageSpace) {
          setCanManagePermissions(false);
          return;
        }
        const [context, models, permissions] = await Promise.all([
          getResourcePermissionContext("knowledge_space", spaceId),
          getGrantablePermissionModels("knowledge_space", spaceId),
          getResourcePermissionGrants("knowledge_space", spaceId, { page_size: 200 }),
        ]);
        if (cancelled) return;
        setCatalogReleaseId(context.catalog_release_id);
        setResourceVersion(context.resource_version);
        setRelationModels(models);
        setCanManagePermissions(context.can_manage_permission);
        resetPermissionDraft(permissions.data.map(permissionEntryToDraftRow), {
          resourceVersion: context.resource_version,
          catalogReleaseId: context.catalog_release_id,
        });
      } catch (error) {
        if (!cancelled)
          setLoadError(
            error instanceof Error
              ? error
              : new Error("Failed to load knowledge space settings"),
          );
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, [mode, resetPermissionDraft, spaceId]);

  const buildResourcePayload = useCallback(() => {
    const customTags = parseKnowledgeSpaceCustomTags(form.autoTagCustomText);
    const autoTagEnabled = autoTagFeatureVisible && form.autoTagEnabled;
    return {
      name: form.name.trim(),
      description: form.description.trim(),
      auth_type: form.visibility,
      is_released:
        form.visibility === VisibilityType.PRIVATE ? false : form.isReleased,
      auto_tag_enabled: autoTagEnabled,
      auto_tag_library_id:
        autoTagEnabled && form.autoTagMode === "library"
          ? form.autoTagLibraryId
          : null,
      auto_tag_custom_tags:
        autoTagEnabled && form.autoTagMode === "custom" ? customTags : null,
    };
  }, [autoTagFeatureVisible, form]);

  const submit = useCallback(async () => {
    if (!form.name.trim() || submitting || (!canEdit && !canManagePermissions))
      return null;
    setSubmitting(true);
    try {
      const payload = buildResourcePayload();
      if (mode === "create") {
        const grants =
          form.visibility === VisibilityType.PRIVATE
            ? []
            : permissionRows
                .map((row) => ({
                  model_key: row.modelKey,
                  subject: {
                    type: row.subjectType,
                    id: String(row.subjectId),
                    ...(row.subjectType === "department"
                      ? {
                          userset_relation: row.includeChildren ? "subtree_member" : null,
                          include_children: Boolean(row.includeChildren),
                        }
                      : {}),
                  },
                }));
        const result = await createSpaceApi({
          ...payload,
          ...(grants.length > 0 && catalogReleaseId != null
            ? {
                creationRequestId: creationRequestIdRef.current,
                initialPermissions: {
                  expected_catalog_release_id: catalogReleaseId,
                  grants,
                },
              }
            : {}),
        });
        setCreatedSpace(result);
        await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
        return result;
      }

      if (!spaceId) return null;
      let result: KnowledgeSpace | null = null;
      if (canEdit) result = await updateSpaceApi(spaceId, payload);
      if (
        form.visibility !== VisibilityType.PRIVATE &&
        canManagePermissions &&
        permissionHasChanges
      ) {
        if (resourceVersion == null || catalogReleaseId == null) return result;
        await mutateResourceGrants("knowledge_space", spaceId, {
          idempotency_key: crypto.randomUUID(),
          expected_resource_version: resourceVersion,
          expected_catalog_release_id: catalogReleaseId,
          changes: permissionDiff.changes,
        });
        resetPermissionDraft(permissionRows);
      } else if (form.visibility === VisibilityType.PRIVATE) {
        resetPermissionDraft([]);
      }
      await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
      return result;
    } finally {
      setSubmitting(false);
    }
  }, [
    buildResourcePayload,
    canEdit,
    canManagePermissions,
    form.name,
    form.visibility,
    mode,
    permissionDiff.changes,
    permissionHasChanges,
    permissionRows,
    queryClient,
    catalogReleaseId,
    resourceVersion,
    resetPermissionDraft,
    spaceId,
    submitting,
  ]);

  const retryInitialPermissions = useCallback(async () => {
    if (!createdSpace || permissionRows.length === 0) return false;
    setPermissionRetryStatus("retrying");
    try {
      const context = await getResourcePermissionContext("knowledge_space", createdSpace.id);
      await mutateResourceGrants("knowledge_space", createdSpace.id, {
        idempotency_key: crypto.randomUUID(),
        expected_resource_version: context.resource_version,
        expected_catalog_release_id: context.catalog_release_id,
        changes: permissionDraft.diff.changes,
      });
      setPermissionRetryStatus("success");
      return true;
    } catch {
      setPermissionRetryStatus("failed");
      return false;
    }
  }, [createdSpace, permissionDraft.diff.changes, permissionRows]);

  return {
    mode,
    form,
    updateForm,
    loading,
    submitting,
    loadError,
    canEdit,
    canManagePermissions,
    relationModels,
    canAddNonUserSubjects: relationModels.length > 0,
    permissionRows,
    permissionDiff,
    permissionHasChanges,
    replacePermissionRows,
    addPermissionRows,
    createdSpace,
    permissionRetryStatus,
    retryInitialPermissions,
    autoTagFeatureVisible,
    tagLibraries,
    autoTagPreview,
    submit,
  };
}
