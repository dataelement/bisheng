import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { generateUUID } from "~/utils";
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
  getAllResourcePermissionGrants,
  getGrantablePermissionModels,
  getMyResourcePermissions,
  getResourcePermissionContext,
  mutateResourceGrants,
} from "~/api/permission";
import type { GrantablePermissionModel } from "~/api/permission";
import { usePermissionDraft } from "~/components/permission/usePermissionDraft";
import type { PermissionDraftRow } from "~/components/permission/usePermissionDraft";

import { createProviderSpace, getSpaceProvider, readProviderSettings, type SpaceProvider } from '~/api/knowledgeProviderSettings';
import { useProviderPreset } from './useProviderPreset';

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
  entry: Awaited<ReturnType<typeof getAllResourcePermissionGrants>>[number],
): PermissionDraftRow {
  return {
    subjectType: entry.subject.type,
    subjectId: Number(entry.subject.id),
    subjectName: entry.subject.name ?? "",
    modelKey: entry.model.key,
    modelName: entry.model.name,
    modelActive: entry.model.active,
    modelLevel: entry.model.level,
    includeChildren: entry.source.include_children,
    assigneeId: entry.assignee_id,
    assigneeVersion: entry.assignee_version,
    sourceType: entry.source.type,
    scope: entry.scope,
    inheritedFrom: entry.inherited_from,
    inheritedFromName: entry.inherited_from_name,
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
  const [provider, setProvider] = useState<SpaceProvider | null>(mode === 'create' ? 'native' : null);
  const [observed, setObserved] = useState<Awaited<ReturnType<typeof readProviderSettings>> | null>(null);
  const baseline = useRef(INITIAL_FORM);
  const preview = useProviderPreset(mode === 'create' && provider === 'weknora');
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [loadError, setLoadError] = useState<Error | null>(null);
  const [isDepartmentSpace, setIsDepartmentSpace] = useState(false);
  const [canEdit, setCanEdit] = useState(mode === "create");
  const [canManagePermissions, setCanManagePermissions] = useState(false);
  const [relationModels, setRelationModels] = useState<GrantablePermissionModel[]>([]);
  const [catalogReleaseId, setCatalogReleaseId] = useState<number | null>(null);
  const creationRequestIdRef = useRef(generateUUID(32));
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
    if (provider !== 'native') return;
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
  }, [mode, provider, updateForm]);

  useEffect(() => {
    let cancelled = false;
    if (
      provider !== "native" || !autoTagFeatureVisible ||
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
  }, [provider, autoTagFeatureVisible, form.autoTagLibraryId, form.autoTagMode]);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    setIsDepartmentSpace(false);

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
        // `getSpaceInfoApi` no longer carries the caller's effective actions,
        // so authorization for this settings page is resolved via the F048
        // my-permissions summary. Both reads are independent, so run them
        // together to keep the page open fast.
        const [space, myPermissions, actualProvider] = await Promise.all([
          getSpaceInfoApi(spaceId),
          getMyResourcePermissions("knowledge_space", spaceId),
          getSpaceProvider(spaceId),
        ]);
        if (cancelled) return;
        const canEditSpace = myPermissions.actions.includes("edit");
        const canManageSpace =
          myPermissions.actions.includes("manage_permission");
        if (!canEditSpace && !canManageSpace && !myPermissions.actions.includes("visible")) {
          throw new Error("Knowledge space settings access denied");
        }
        if (actualProvider === 'weknora') {
          const settings = await readProviderSettings(spaceId);
          if (cancelled) return;
          setObserved(settings);
        }
        setProvider(actualProvider);
        setCanEdit(actualProvider === 'native' && canEditSpace);
        setIsDepartmentSpace(space.departmentId != null || space.spaceKind === "department");
        baseline.current = {
          name: space.name,
          description: space.description ?? "",
          visibility: space.visibility,
          isReleased: space.isReleased,
          autoTagEnabled: Boolean(space.autoTagEnabled),
          autoTagMode: space.autoTagMode ?? "library",
          autoTagLibraryId: space.autoTagLibraryId ?? null,
          autoTagCustomText: (space.autoTagCustomTags ?? []).join("\n"),
        };
        setForm(baseline.current);

        if (!canManageSpace) {
          setCanManagePermissions(false);
          return;
        }
        const [context, models, permissions] = await Promise.all([
          getResourcePermissionContext("knowledge_space", spaceId),
          getGrantablePermissionModels("knowledge_space", spaceId),
          getAllResourcePermissionGrants("knowledge_space", spaceId),
        ]);
        if (cancelled) return;
        setCatalogReleaseId(context.catalog_release_id);
        setRelationModels(models);
        setCanManagePermissions(context.can_manage_permission);
        resetPermissionDraft(permissions.map(permissionEntryToDraftRow), {
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

  const tagsChanged = form.autoTagEnabled !== baseline.current.autoTagEnabled ||
    form.autoTagLibraryId !== baseline.current.autoTagLibraryId || form.autoTagMode !== baseline.current.autoTagMode ||
    form.autoTagCustomText !== baseline.current.autoTagCustomText;
  const includeTags = provider === 'native' && (mode === 'create' || (autoTagFeatureVisible && tagsChanged));
  const buildResourcePayload = useCallback(() => {
    const creating = mode === 'create';
    const previous = baseline.current;
    const autoTagEnabled = autoTagFeatureVisible && form.autoTagEnabled;
    return {
      ...(creating || form.name !== previous.name ? { name: form.name.trim() } : {}),
      ...(creating || form.description !== previous.description ? { description: form.description.trim() } : {}),
      ...(creating || form.visibility !== previous.visibility ? { auth_type: form.visibility } : {}),
      ...(creating || form.visibility !== previous.visibility || form.isReleased !== previous.isReleased
        ? { is_released: form.visibility !== VisibilityType.PRIVATE && form.isReleased } : {}),
      ...(includeTags ? {
        auto_tag_enabled: autoTagEnabled,
        auto_tag_library_id: autoTagEnabled && form.autoTagMode === 'library' ? form.autoTagLibraryId : null,
        auto_tag_custom_tags: autoTagEnabled && form.autoTagMode === 'custom' ? parseKnowledgeSpaceCustomTags(form.autoTagCustomText) : null,
      } : {}),
    };
  }, [autoTagFeatureVisible, form, includeTags, mode]);

  const submit = useCallback(async () => {
    if (loading || loadError || !provider || !form.name.trim() || submitting || (!canEdit && !(canManagePermissions && permissionHasChanges))) return null;
    setSubmitting(true);
    try {
      const payload = buildResourcePayload();
      if (mode === "create") {
        if (provider === 'weknora') {
          if (!preview.preset) return null;
          const receipt = await createProviderSpace(preview.preset, creationRequestIdRef.current, {
            name: form.name.trim(), description: form.description.trim(), auth_type: form.visibility,
            is_released: form.visibility !== VisibilityType.PRIVATE && form.isReleased,
          });
          await queryClient.invalidateQueries({ queryKey: ['knowledgeSpaces'] });
          return receipt;
        }
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
          ...payload, name: form.name.trim(), auth_type: form.visibility,
          creationRequestId: creationRequestIdRef.current,
          ...(grants.length > 0 && catalogReleaseId != null
            ? {
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
      if (provider === 'native' && canEdit && Object.keys(payload).length) result = await updateSpaceApi(spaceId, payload);
      if (
        form.visibility !== VisibilityType.PRIVATE &&
        canManagePermissions &&
        permissionHasChanges
      ) {
        const latestContext = await getResourcePermissionContext("knowledge_space", spaceId);
        await mutateResourceGrants("knowledge_space", spaceId, {
          idempotency_key: generateUUID(32),
          expected_resource_version: latestContext.resource_version,
          expected_catalog_release_id: latestContext.catalog_release_id,
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
    form, loading, loadError, provider, preview.preset,
    mode,
    permissionDiff.changes,
    permissionHasChanges,
    permissionRows,
    queryClient,
    catalogReleaseId,
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
        idempotency_key: generateUUID(32),
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
    provider, setProvider, preview, observed, includeTags,
    form,
    updateForm,
    loading,
    submitting,
    loadError,
    canEdit,
    isDepartmentSpace,
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
    autoTagFeatureVisible: provider === 'native' && autoTagFeatureVisible,
    tagLibraries,
    autoTagPreview,
    submit,
  };
}
