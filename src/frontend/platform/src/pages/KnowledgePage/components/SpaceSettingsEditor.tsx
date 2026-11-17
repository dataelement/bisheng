import { Button, Select, Tabs, Textarea, toast } from "@bisheng/ui";
import { useQuery } from "@tanstack/react-query";
import { isEqual } from "lodash-es";
import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useTranslation } from "react-i18next";
import { Outlined } from "bisheng-icons";
import {
  SpaceSettingsAccessSelector,
  SpaceSettingsSectionHeader,
  SpaceSettingsSwitchRow,
} from "./SpaceSettingsControls";
import { SpaceBasicFields } from "./SpaceBasicFields";
import { SpacePanelFrame } from "./SpacePanelFrame";
import { ProcessingDefaultsFields } from "./ProcessingDefaultsDialog";
import { SpaceProcessingPanel } from "./SpaceProcessingDialog";
import { useProcessingDefaultsDraft } from "./useProcessingDefaultsDraft";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { knowledgeSpaceApi } from "@/controllers/API/knowledgeSpace";
import { updateSpaceSettings } from "@/controllers/API/knowledgeSpaceSettings";
import { getMyResourcePermissionsApi } from "@/controllers/API/permission";
import {
  getKnowledgeSpaceAutoTagVisibilityApi,
  getKnowledgeSpaceTagLibrariesApi,
  getKnowledgeSpaceTagLibraryApi,
} from "@/controllers/API/knowledgeSpaceTagLibrary";
import {
  knowledgeQueryKeys,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import {
  parseSpaceTags,
  spaceSettingsDraft,
  spaceSettingsPayload,
  validSpaceSettings,
  type SpaceSettingsDraft,
} from "./spaceSettingsForm";
interface SpaceSettingsEditorProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  onSaved: () => void | Promise<void>;
  onBack?: () => void;
}
export function SpaceSettingsEditor(props: SpaceSettingsEditorProps) {
  return (
    <SettingsEditor
      key={JSON.stringify([props.scope, props.spaceId])}
      {...props}
    />
  );
}
function SettingsEditor({
  scope,
  spaceId,
  onSaved,
  onBack,
}: SpaceSettingsEditorProps) {
  const { t } = useTranslation("knowledge");
  const labels = useSelectLabels();
  const instance = useId();
  const active = useRef(true),
    locked = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const [draft, setDraft] = useState<SpaceSettingsDraft | null>(null);
  const [savedDraft, setSavedDraft] = useState<SpaceSettingsDraft | null>(null);
  const [partialSave, setPartialSave] = useState(false);
  const [busy, setBusy] = useState(false);
  const [tagsTouched, setTagsTouched] = useState(false);
  const [original, setOriginal] =
    useState<Awaited<ReturnType<typeof knowledgeSpaceApi.getSpaceInfo>>>();
  const info = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "settings-opening",
      instance,
    ],
    queryFn: () => knowledgeSpaceApi.getSpaceInfo(spaceId),
    retry: false,
    cacheTime: 0,
    refetchOnWindowFocus: false,
    onSuccess: (value) => {
      if (active.current) {
        setOriginal(value);
        const initial = spaceSettingsDraft(value);
        setSavedDraft((previous) => previous ?? initial);
        setDraft((previous) => previous ?? initial);
      }
    },
  });
  const permission = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.space(scope, spaceId),
      "settings-actions",
      instance,
    ],
    queryFn: () =>
      getMyResourcePermissionsApi("knowledge_space", String(spaceId)),
    retry: false,
    cacheTime: 0,
  });
  const feature = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(scope), "auto-tag-visibility"],
    queryFn: getKnowledgeSpaceAutoTagVisibilityApi,
    retry: false,
    refetchOnWindowFocus: false,
  });
  const libraries = useQuery({
    queryKey: [...knowledgeQueryKeys.scope(scope), "auto-tag-libraries"],
    queryFn: () =>
      getKnowledgeSpaceTagLibrariesApi({ page: 1, page_size: 200 }),
    enabled: feature.data?.visible === true,
    retry: false,
  });
  const library = useQuery({
    queryKey: [
      ...knowledgeQueryKeys.scope(scope),
      "auto-tag-library",
      draft?.libraryId,
    ],
    queryFn: () => getKnowledgeSpaceTagLibraryApi(draft!.libraryId!),
    enabled:
      feature.data?.visible === true &&
      draft?.tagMode === "library" &&
      Boolean(draft.libraryId),
    retry: false,
  });
  const canEdit = permission.data?.actions.includes("edit") === true;
  const processing = useProcessingDefaultsDraft(
    scope,
    spaceId,
    knowledgeSpaceApi,
    canEdit,
  );
  const canShare =
    canEdit && permission.data?.actions.includes("manage_permission") === true;
  const department =
    original?.space_kind === "department" || original?.department_id != null;
  const options =
    libraries.data?.data
      .filter((row) => Number.isSafeInteger(row.id) && row.id > 0)
      .map((row) => ({ value: row.id, label: row.name })) ?? [];
  if (library.data && !options.some((row) => row.value === library.data.id))
    options.push({ value: library.data.id, label: library.data.name });
  useEffect(() => {
    active.current = true;
    const own = new AbortController();
    controller.current = own;
    return () => {
      active.current = false;
      controller.current?.abort();
    };
  }, []);
  useEffect(() => {
    if (active.current && !busy && permission.isSuccess && !canEdit) onBack?.();
  }, [busy, canEdit, onBack, permission.isSuccess]);
  useEffect(() => {
    const error =
      info.error ||
      permission.error ||
      feature.error ||
      libraries.error ||
      library.error;
    if (error) showApiError(error);
  }, [
    info.error,
    permission.error,
    feature.error,
    libraries.error,
    library.error,
  ]);
  const update = useCallback(
    <K extends keyof SpaceSettingsDraft>(
      key: K,
      value: SpaceSettingsDraft[K],
    ) => {
      setDraft((current) => (current ? { ...current, [key]: value } : current));
    },
    [],
  );
  const setTag = <K extends keyof SpaceSettingsDraft>(
    key: K,
    value: SpaceSettingsDraft[K],
  ) => {
    setTagsTouched(true);
    update(key, value);
  };
  const chooseAccess = (value: "private" | "shared") => {
    if (!canShare || busy || !draft || (value === "private" && department))
      return;
    if (value === "private" && draft.auth !== "private") {
      const signal = controller.current?.signal;
      bsConfirm({
        desc: t("settings_ext.private_notice"),
        signal,
        onOk: () => {
          if (active.current && !signal?.aborted) update("auth", "private");
        },
      });
    } else if (value === "shared" && draft.auth === "private")
      update("auth", "approval");
  };
  const saveTags = feature.data?.visible === true && tagsTouched;
  const basicPayload =
    draft && original
      ? spaceSettingsPayload(draft, original, canShare, saveTags)
      : null;
  const basicChanged =
    basicPayload && original && savedDraft &&
    !isEqual(basicPayload, spaceSettingsPayload(savedDraft, original, canShare, saveTags));
  const canSave =
    canEdit &&
    (basicChanged || processing.dirty) &&
    (!basicChanged || (draft && validSpaceSettings(draft, saveTags))) &&
    (!processing.dirty || processing.valid);
  const handleSave = async () => {
    if (!active.current || locked.current || !canSave) return;
    locked.current = true;
    setBusy(true);
    let savedProcessingOnly = false;
    try {
      if (processing.dirty) {
        if (!(await processing.save()) || !active.current) return;
        savedProcessingOnly = true;
      }
      if (basicChanged && draft && basicPayload) {
        await updateSpaceSettings(spaceId, basicPayload);
        if (!active.current) return;
        const saved = {
          ...draft,
          name: basicPayload.name,
          description: basicPayload.description,
          released: basicPayload.is_released,
          customText: basicPayload.auto_tag_custom_tags?.join("\n") ?? draft.customText,
        };
        setSavedDraft(saved);
        setDraft(saved);
        setTagsTouched(false);
      }
      savedProcessingOnly = false;
      setPartialSave(false);
      toast.show({ type: "success", message: t("detail.saved") });
      await onSaved();
      if (active.current) onBack?.();
    } catch (error) {
      if (active.current) {
        if (savedProcessingOnly) setPartialSave(true);
        showApiError(error);
      }
    } finally {
      locked.current = false;
      if (active.current) setBusy(false);
    }
  };
  const handleCancel = () => {
    if (locked.current) return;
    controller.current?.abort();
    controller.current = new AbortController();
    setDraft(savedDraft);
    setTagsTouched(false);
    setPartialSave(false);
    processing.reset();
    onBack?.();
  };
  const infoFailed = info.isError || info.isSuccess;
  const showAdvanced =
    canEdit ||
    (draft && (feature.isError || feature.data?.visible));
  const fields = (
    <>
      {draft && original ? (
        <fieldset disabled={!canEdit || busy} className="min-w-0 space-y-6">
          <SpaceSettingsSectionHeader
            kind="basic"
            title={t("settings_ext.basic")}
          />
          <div className="px-6 max-[768px]:px-0">
            <SpaceBasicFields
              mode="settings"
              compact
              name={draft.name}
              description={draft.description}
              disabled={!canEdit || busy}
              onNameChange={(value) => update("name", value)}
              onDescriptionChange={(value) => update("description", value)}
            />
          </div>
        </fieldset>
      ) : (
        <div role={infoFailed ? "alert" : "status"}>
          <p>{t(infoFailed ? "f118.load_failed" : "f118.loading_space")}</p>
          {infoFailed && (
            <Button onClick={() => { void info.refetch(); }}>
              {t("retry")}
            </Button>
          )}
        </div>
      )}
      {showAdvanced && (
        <section className="space-y-6">
          <SpaceSettingsSectionHeader
            kind="advanced"
            title={t("f118.advanced_settings")}
          />
          <div className="min-w-0 space-y-6 px-6 max-[768px]:px-0">
            {canEdit && (
              <>
                <SpaceProcessingPanel
                  scope={scope}
                  spaceId={spaceId}
                  mode="embedding"
                  presentation="inline"
                  onSaved={() => { void onSaved(); }}
                />
                <SpacePanelFrame title={t("f118.defaults_title")} presentation="inline">
                  <ProcessingDefaultsFields form={processing} compact disabled={busy} />
                </SpacePanelFrame>
              </>
            )}
            {draft && feature.isError && (
              <div role="alert">
                <p>{t("f118.load_failed")}</p>
                <Button
                  onClick={() => {
                    void feature.refetch();
                  }}
                >
                  {t("retry")}
                </Button>
              </div>
            )}
            {draft && feature.data?.visible && (
              <fieldset disabled={!canEdit || busy} className="min-w-0 space-y-4">
                <SpaceSettingsSwitchRow
                  label={t("settings_ext.auto_tag")}
                  checked={draft.autoTag}
                  disabled={!canEdit || busy}
                  onCheckedChange={(value) => setTag("autoTag", value)}
                />
                {draft.autoTag && (
                  <Tabs
                    activeKey={draft.tagMode}
                    onChange={(value) => {
                      if (value === "library" || value === "custom")
                        setTag("tagMode", value);
                    }}
                    items={[
                      {
                        key: "library",
                        label: t("settings_ext.library"),
                        children: (
                          <div className="mt-3 space-y-2">
                            <Select
                              {...labels}
                              aria-label={t("settings_ext.library")}
                              loading={libraries.isFetching}
                              options={options}
                              value={draft.libraryId ?? undefined}
                              onChange={(value) => {
                                if (value != null)
                                  setTag("libraryId", Number(value));
                              }}
                            />
                            {libraries.isError && (
                              <Button
                                onClick={() => {
                                  void libraries.refetch();
                                }}
                              >
                                {t("retry")}
                              </Button>
                            )}
                            {library.isError && (
                              <Button
                                onClick={() => {
                                  void library.refetch();
                                }}
                              >
                                {t("retry")}
                              </Button>
                            )}
                            {library.data && (
                              <div className="flex flex-wrap gap-2 text-body-sm text-text-3">
                                {library.data.tags.slice(0, 20).map((tag) => (
                                  <span
                                    key={tag}
                                    className="rounded-full bg-fill-2 px-2 py-1"
                                  >
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            )}
                          </div>
                        ),
                      },
                      {
                        key: "custom",
                        label: t("settings_ext.custom"),
                        children: (
                          <div className="mt-3 space-y-2">
                            <div className="flex items-center justify-between text-body-sm text-text-3">
                              <span>
                                {parseSpaceTags(draft.customText).length}/200
                              </span>
                              <label className="inline-flex cursor-pointer items-center gap-1 text-blue-500 hover:underline">
                                <Outlined.Upload className="size-4" />
                                {t("settings_ext.upload_txt")}
                                <input
                                  type="file"
                                  accept=".txt"
                                  className="hidden"
                                  onChange={(event) => {
                                    const file = event.target.files?.[0];
                                    event.target.value = "";
                                    if (!file) return;
                                    const signal = controller.current?.signal;
                                    const reader = new FileReader();
                                    reader.onload = () => {
                                      if (active.current && !signal?.aborted)
                                        setTag(
                                          "customText",
                                          typeof reader.result === "string"
                                            ? reader.result
                                            : "",
                                        );
                                    };
                                    reader.onerror = () => {
                                      if (active.current && !signal?.aborted)
                                        showApiError(reader.error);
                                    };
                                    reader.readAsText(file);
                                  }}
                                />
                              </label>
                            </div>
                            <Textarea
                              aria-label={t("settings_ext.custom_tags")}
                              value={draft.customText}
                              onChange={(event) =>
                                setTag("customText", event.target.value)
                              }
                              rows={5}
                            />
                          </div>
                        ),
                      },
                    ]}
                  />
                )}
              </fieldset>
            )}
          </div>
        </section>
      )}
      {draft && original && (
          <fieldset disabled={busy || !canShare} className="min-w-0 space-y-6">
            <SpaceSettingsSectionHeader
              kind="permission"
              title={t("settings_ext.access")}
            />
            <div className="space-y-4 px-6 max-[768px]:px-0">
              <div className="space-y-2">
                <p className="font-medium text-text-1">
                  <span className="mr-1 text-danger">*</span>
                  {t("settings_ext.access")}
                </p>
                <SpaceSettingsAccessSelector
                  value={draft.auth === "private" ? "private" : "shared"}
                  onValueChange={chooseAccess}
                  disabled={!canShare || busy}
                  privateDisabled={department}
                  label={t("settings_ext.access")}
                  privateLabel={t("settings_ext.private")}
                  privateDescription={t(
                    department
                      ? "settings_ext.department_notice"
                      : "settings_ext.private_hint",
                  )}
                  sharedLabel={t("settings_ext.shared")}
                  sharedDescription={t("settings_ext.shared_hint")}
                />
              </div>
              {draft.auth !== "private" && (
                <>
                  <SpaceSettingsSwitchRow
                    required
                    label={t("settings_ext.review")}
                    description={t("settings_ext.review_hint")}
                    checked={draft.auth === "approval"}
                    disabled={!canShare || busy}
                    onCheckedChange={(value) =>
                      update("auth", value ? "approval" : "public")
                    }
                  />
                  <SpaceSettingsSwitchRow
                    required
                    label={t("settings_ext.publish")}
                    description={t("settings_ext.publish_hint")}
                    checked={draft.released}
                    disabled={!canShare || busy}
                    onCheckedChange={(value) => update("released", value)}
                  />
                </>
              )}
            </div>
          </fieldset>
      )}
      {permission.isError && (
        <Button onClick={() => { void permission.refetch(); }}>
          {t("retry")}
        </Button>
      )}
    </>
  );
  const footer = (
    <>
      {partialSave && (
        <p role="status" className={onBack
          ? "basis-full text-center text-body-sm text-text-2"
          : "mr-auto text-body-sm text-text-2"}>
          {t("detail.processing_saved_settings_failed")}
        </p>
      )}
      <Button
        variant="outlined"
        color="default"
        disabled={busy}
        onClick={handleCancel}
      >
        {t("cancel")}
      </Button>
      <Button
        loading={busy}
        disabled={busy || !canSave}
        onClick={() => { void handleSave(); }}
      >
        {t("confirm")}
      </Button>
    </>
  );
  if (onBack) {
    return (
      <SpacePanelFrame
        title={t("detail.settings")}
        presentation="page"
        busy={busy}
        back={{ label: t("back"), onClick: handleCancel }}
        footer={footer}
      >
        {canEdit ? (
          <div className="space-y-6 text-body">{fields}</div>
        ) : permission.isError ? (
          <div role="alert" className="space-y-3">
            <p>{t("f118.load_failed")}</p>
            <Button onClick={() => { void permission.refetch(); }}>{t("retry")}</Button>
          </div>
        ) : (
          <p role="status">{t(permission.isSuccess ? "noOperationPermission" : "f118.loading_space")}</p>
        )}
      </SpacePanelFrame>
    );
  }
  return (
    <section className="mx-auto w-full min-w-0 max-w-[648px] space-y-6 py-6 text-body">
      <h2 className="sr-only">{t("f118.edit_space")}</h2>
      {fields}
      {canEdit && (draft || processing.draft) && (
        <footer className="flex min-h-16 flex-wrap items-center justify-end gap-3 border-t border-border-base py-2">
          {footer}
        </footer>
      )}
    </section>
  );
}
