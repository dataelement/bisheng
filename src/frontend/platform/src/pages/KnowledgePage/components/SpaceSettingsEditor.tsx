import { Button, Input, Select, Tabs, Textarea, toast } from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Outlined } from "bisheng-icons";
import {
  SpaceSettingsAccessSelector,
  SpaceSettingsSectionHeader,
  SpaceSettingsSwitchRow,
} from "./SpaceSettingsControls";
import { PermissionDialog } from "@/components/bs-comp/permission/PermissionDialog";
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
  getSpaceTextLength,
  truncateSpaceText,
  SPACE_NAME_LIMIT,
  SPACE_DESCRIPTION_LIMIT,
  spaceSettingsDraft,
  spaceSettingsPayload,
  validSpaceSettings,
  type SpaceSettingsDraft,
} from "./spaceSettingsForm";
interface SpaceSettingsEditorProps {
  scope: KnowledgeQueryScope;
  spaceId: number;
  onSaved: () => void | Promise<void>;
}
export function SpaceSettingsEditor(props: SpaceSettingsEditorProps) {
  return (
    <SettingsEditor
      key={JSON.stringify([props.scope, props.spaceId])}
      {...props}
    />
  );
}
function SettingsEditor({ scope, spaceId, onSaved }: SpaceSettingsEditorProps) {
  const { t } = useTranslation("knowledge");
  const labels = useSelectLabels(),
    instance = useId(),
    client = useQueryClient();
  const active = useRef(true),
    locked = useRef(false);
  const controller = useRef<AbortController | null>(null);
  const nameComposing = useRef(false),
    descriptionComposing = useRef(false);
  const [draft, setDraft] = useState<SpaceSettingsDraft | null>(null);
  const [busy, setBusy] = useState(false),
    [permissionOpen, setPermissionOpen] = useState(false),
    [tagsTouched, setTagsTouched] = useState(false);
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
        setDraft((previous) => previous ?? spaceSettingsDraft(value));
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
      own.abort();
    };
  }, []);
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
      bsConfirm({
        desc: t("settings_ext.private_notice"),
        signal: controller.current?.signal,
        onOk: () => {
          if (active.current) update("auth", "private");
        },
      });
    } else if (value === "shared" && draft.auth === "private")
      update("auth", "approval");
  };
  const handleSave = async () => {
    if (
      !active.current ||
      locked.current ||
      !draft ||
      !original ||
      !canEdit ||
      !validSpaceSettings(draft, tagsTouched)
    )
      return;
    locked.current = true;
    setBusy(true);
    try {
      await updateSpaceSettings(
        spaceId,
        spaceSettingsPayload(
          draft,
          original,
          canShare,
          feature.data?.visible === true && tagsTouched,
        ),
      );
      if (!active.current) return;
      await client.invalidateQueries({
        queryKey: knowledgeQueryKeys.scope(scope),
      });
      if (!active.current) return;
      await onSaved();
      if (active.current) {
        setTagsTouched(false);
        toast.show({ type: "success", message: t("detail.saved") });
      }
    } catch (error) {
      if (active.current) showApiError(error);
    } finally {
      locked.current = false;
      if (active.current) setBusy(false);
    }
  };
  if (!draft || !original)
    return (
      <div role={info.isError || info.isSuccess ? "alert" : "status"}>
        <p>
          {t(
            info.isError || info.isSuccess
              ? "f118.load_failed"
              : "f118.loading_space",
          )}
        </p>
        {(info.isError || info.isSuccess) && (
          <Button
            onClick={() => {
              void info.refetch();
            }}
          >
            {t("retry")}
          </Button>
        )}
      </div>
    );
  return (
    <section className="mx-auto w-full min-w-0 max-w-[648px] space-y-6 py-6 text-body">
      <h2 className="sr-only">{t("f118.edit_space")}</h2>
      <fieldset disabled={!canEdit || busy} className="min-w-0 space-y-6">
        <SpaceSettingsSectionHeader
          kind="basic"
          title={t("settings_ext.basic")}
        />
        <div className="space-y-4 px-6 max-[768px]:px-0">
          <label className="block space-y-2">
            <span className="font-medium text-text-1">
              <span className="mr-1 text-danger">*</span>
              {t("f118.space_name")}
            </span>
            <Input
              aria-label={t("f118.space_name")}
              value={draft.name}
              status={
                getSpaceTextLength(draft.name) > SPACE_NAME_LIMIT
                  ? "error"
                  : "default"
              }
              suffix={
                <span
                  aria-hidden
                  className={`text-body-sm ${getSpaceTextLength(draft.name) > SPACE_NAME_LIMIT ? "text-danger" : "text-text-3"}`}
                >
                  {Math.ceil(getSpaceTextLength(draft.name))}/{SPACE_NAME_LIMIT}
                </span>
              }
              onCompositionStart={() => {
                nameComposing.current = true;
              }}
              onCompositionEnd={(event) => {
                nameComposing.current = false;
                update(
                  "name",
                  truncateSpaceText(
                    event.currentTarget.value,
                    SPACE_NAME_LIMIT,
                  ),
                );
              }}
              onChange={(event) =>
                update(
                  "name",
                  nameComposing.current
                    ? event.target.value
                    : truncateSpaceText(event.target.value, SPACE_NAME_LIMIT),
                )
              }
            />
          </label>
          <label className="block space-y-2">
            <span className="font-medium text-text-1">
              {t("f118.space_description")}
            </span>
            <Textarea
              rows={3}
              value={draft.description}
              onCompositionStart={() => {
                descriptionComposing.current = true;
              }}
              onCompositionEnd={(event) => {
                descriptionComposing.current = false;
                update(
                  "description",
                  truncateSpaceText(
                    event.currentTarget.value,
                    SPACE_DESCRIPTION_LIMIT,
                  ),
                );
              }}
              onChange={(event) =>
                update(
                  "description",
                  descriptionComposing.current
                    ? event.target.value
                    : truncateSpaceText(
                        event.target.value,
                        SPACE_DESCRIPTION_LIMIT,
                      ),
                )
              }
            />
          </label>
        </div>
        {feature.isError && (
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
        {feature.data?.visible && (
          <section className="space-y-6">
            <SpaceSettingsSectionHeader
              kind="advanced"
              title={t("f118.advanced_settings")}
            />
            <div className="space-y-4 px-6 max-[768px]:px-0">
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
                                  const reader = new FileReader();
                                  reader.onload = () => {
                                    if (active.current)
                                      setTag(
                                        "customText",
                                        typeof reader.result === "string"
                                          ? reader.result
                                          : "",
                                      );
                                  };
                                  reader.onerror = () => {
                                    if (active.current)
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
            </div>
          </section>
        )}
      </fieldset>
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
          {canShare && (
            <Button
              color="default"
              variant="outlined"
              onClick={() => setPermissionOpen(true)}
            >
              {t("managePermission", { ns: "permission" })}
            </Button>
          )}
        </div>
      </fieldset>
      {permission.isError && (
        <Button
          onClick={() => {
            void permission.refetch();
          }}
        >
          {t("retry")}
        </Button>
      )}
      <footer className="flex h-16 items-center justify-end gap-3 border-t border-border-base">
        <Button
          loading={busy}
          disabled={busy || !canEdit || !validSpaceSettings(draft, tagsTouched)}
          onClick={() => {
            void handleSave();
          }}
        >
          {t("confirm")}
        </Button>
      </footer>
      {permissionOpen && canShare && (
        <PermissionDialog
          open
          onOpenChange={setPermissionOpen}
          resourceType="knowledge_space"
          resourceId={String(spaceId)}
          resourceName={original.name}
        />
      )}
    </section>
  );
}
