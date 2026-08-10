import { useCallback, useEffect, useMemo, useState } from "react";
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
  authorizeResource,
  checkPermission,
  getCreationGrantableRelationModels,
  getGrantableRelationModels,
  getResourcePermissions,
} from "~/api/permission";
import type { RelationModel, SelectedSubject } from "~/api/permission";
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
  isReleased: false,
  autoTagEnabled: false,
  autoTagMode: "library",
  autoTagLibraryId: null,
  autoTagCustomText: "",
};

function permissionEntryToDraftRow(
  entry: Awaited<ReturnType<typeof getResourcePermissions>>[number],
): PermissionDraftRow {
  return {
    subjectType: entry.subject_type,
    subjectId: entry.subject_id,
    subjectName: entry.subject_name ?? "",
    relation: entry.relation,
    modelId: entry.model_id,
    includeChildren: entry.include_children,
    immutableCreator: entry.is_creator === true,
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
  const [submitError, setSubmitError] = useState<Error | null>(null);
  const [canEdit, setCanEdit] = useState(mode === "create");
  const [canManagePermissions, setCanManagePermissions] = useState(false);
  const [relationModels, setRelationModels] = useState<RelationModel[]>([]);
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
          const models =
            await getCreationGrantableRelationModels("knowledge_space");
          if (!cancelled) {
            setRelationModels(models);
            setCanManagePermissions(models.length > 0);
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
        const [space, editResult, manageResult] = await Promise.all([
          getSpaceInfoApi(spaceId),
          checkPermission("knowledge_space", spaceId, "can_edit", "edit_space"),
          checkPermission(
            "knowledge_space",
            spaceId,
            "can_manage",
            "manage_space_relation",
          ),
        ]);
        if (cancelled) return;
        setCanEdit(Boolean(editResult.allowed));
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

        if (!manageResult.allowed) {
          setCanManagePermissions(false);
          return;
        }
        const [models, permissions] = await Promise.all([
          getGrantableRelationModels("knowledge_space", spaceId),
          getResourcePermissions("knowledge_space", spaceId),
        ]);
        if (cancelled) return;
        setRelationModels(models);
        setCanManagePermissions(true);
        resetPermissionDraft(permissions.map(permissionEntryToDraftRow));
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

  const defaultNonOwnerRelationModel = useMemo(
    () =>
      relationModels.find((model) => model.relation === "editor") ??
      relationModels.find((model) => model.relation === "viewer") ??
      relationModels.find((model) => model.relation !== "owner"),
    [relationModels],
  );
  const defaultUserRelationModel =
    defaultNonOwnerRelationModel ?? relationModels[0];

  const addSubjects = useCallback(
    (subjects: SelectedSubject[]) => {
      addPermissionRows(
        subjects.flatMap((subject) => {
          const model =
            subject.type === "user"
              ? defaultUserRelationModel
              : defaultNonOwnerRelationModel;
          if (!model) return [];
          return [
            {
              subjectType: subject.type,
              subjectId: subject.id,
              subjectName: subject.name,
              relation: model.relation,
              modelId: model.id,
              includeChildren:
                subject.type === "department"
                  ? (subject.include_children ?? true)
                  : undefined,
            },
          ];
        }),
      );
    },
    [addPermissionRows, defaultNonOwnerRelationModel, defaultUserRelationModel],
  );

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
    setSubmitError(null);
    try {
      const payload = buildResourcePayload();
      if (mode === "create") {
        const grants =
          form.visibility === VisibilityType.PRIVATE
            ? []
            : permissionRows
                .filter((row) => !row.immutableCreator)
                .map((row) => ({
                  subject_type: row.subjectType,
                  subject_id: row.subjectId,
                  relation: row.relation,
                  ...(row.modelId ? { model_id: row.modelId } : {}),
                  ...(row.includeChildren === undefined
                    ? {}
                    : { include_children: row.includeChildren }),
                }));
        const result = await createSpaceApi({
          ...payload,
          ...(grants.length > 0 ? { initialPermissions: { grants } } : {}),
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
        await authorizeResource(
          "knowledge_space",
          spaceId,
          permissionDiff.grants,
          permissionDiff.revokes,
        );
        resetPermissionDraft(permissionRows);
      } else if (form.visibility === VisibilityType.PRIVATE) {
        resetPermissionDraft([]);
      }
      await queryClient.invalidateQueries({ queryKey: ["knowledgeSpaces"] });
      return result;
    } catch (error) {
      const normalized =
        error instanceof Error
          ? error
          : new Error("Failed to save knowledge space settings");
      setSubmitError(normalized);
      throw normalized;
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
    permissionDiff.grants,
    permissionDiff.revokes,
    permissionHasChanges,
    permissionRows,
    queryClient,
    resetPermissionDraft,
    spaceId,
    submitting,
  ]);

  const retryInitialPermissions = useCallback(async () => {
    if (!createdSpace || permissionRows.length === 0) return false;
    setPermissionRetryStatus("retrying");
    try {
      const grants = permissionRows
        .filter((row) => !row.immutableCreator)
        .map((row) => ({
          subject_type: row.subjectType,
          subject_id: row.subjectId,
          relation: row.relation,
          ...(row.modelId ? { model_id: row.modelId } : {}),
          ...(row.includeChildren === undefined
            ? {}
            : { include_children: row.includeChildren }),
        }));
      await authorizeResource("knowledge_space", createdSpace.id, grants, []);
      setPermissionRetryStatus("success");
      return true;
    } catch {
      setPermissionRetryStatus("failed");
      return false;
    }
  }, [createdSpace, permissionRows]);

  return {
    mode,
    form,
    updateForm,
    loading,
    submitting,
    loadError,
    submitError,
    canEdit,
    canManagePermissions,
    relationModels,
    canAddNonUserSubjects: Boolean(defaultNonOwnerRelationModel),
    permissionRows,
    permissionDiff,
    permissionHasChanges,
    replacePermissionRows,
    addSubjects,
    createdSpace,
    permissionRetryStatus,
    retryInitialPermissions,
    autoTagFeatureVisible,
    tagLibraries,
    autoTagPreview,
    submit,
  };
}
