import {
  Button,
  Input,
  Select,
  Checkbox,
  Tabs,
  Textarea,
  toast,
} from "@bisheng/ui";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
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
    <section className="space-y-6">
      <fieldset disabled={!canEdit || busy} className="space-y-4">
        <h2 className="text-heading-sm font-medium">{t("f118.edit_space")}</h2>
        <label className="block space-y-2">
          <span>{t("f118.space_name")}</span>
          <Input
            value={draft.name}
            maxLength={200}
            onChange={(event) => update("name", event.target.value)}
          />
        </label>
        <label className="block space-y-2">
          <span>{t("f118.space_description")}</span>
          <Textarea
            rows={5}
            maxLength={200}
            value={draft.description}
            onChange={(event) => update("description", event.target.value)}
          />
        </label>
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
          <div className="space-y-4">
            <h3 className="rounded-lg bg-muted p-3 font-medium">
              {t("f118.advanced_settings")}
            </h3>
            <label className="flex items-center justify-between">
              <span>{t("settings_ext.auto_tag")}</span>
              <Checkbox
                checked={draft.autoTag}
                onCheckedChange={(value) => setTag("autoTag", value === true)}
              />
            </label>
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
                      <div className="space-y-3">
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
                          <p className="text-sm text-text-secondary">
                            {library.data.tags.slice(0, 20).join(" / ")}
                          </p>
                        )}
                      </div>
                    ),
                  },
                  {
                    key: "custom",
                    label: t("settings_ext.custom"),
                    children: (
                      <div className="space-y-2">
                        <p>{parseSpaceTags(draft.customText).length}/200</p>
                        <Textarea
                          aria-label={t("settings_ext.custom_tags")}
                          value={draft.customText}
                          onChange={(event) =>
                            setTag("customText", event.target.value)
                          }
                          rows={5}
                        />
                        <label className="inline-block cursor-pointer text-primary">
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
                                if (active.current) showApiError(reader.error);
                              };
                              reader.readAsText(file);
                            }}
                          />
                        </label>
                      </div>
                    ),
                  },
                ]}
              />
            )}
          </div>
        )}
      </fieldset>
      <fieldset disabled={busy || !canShare} className="space-y-4">
        <h3 className="rounded-lg bg-muted p-3 font-medium">
          {t("settings_ext.access")}
        </h3>
        <div className="flex gap-3">
          <Button
            variant={draft.auth === "private" ? "solid" : "outlined"}
            disabled={!canShare || busy || department}
            onClick={() => chooseAccess("private")}
          >
            {t("settings_ext.private")}
          </Button>
          <Button
            variant={draft.auth !== "private" ? "solid" : "outlined"}
            onClick={() => chooseAccess("shared")}
          >
            {t("settings_ext.shared")}
          </Button>
        </div>
        {department && (
          <p className="text-sm text-text-secondary">
            {t("settings_ext.department_notice")}
          </p>
        )}
        {draft.auth !== "private" && (
          <>
            <label className="flex items-center justify-between">
              <span>{t("settings_ext.review")}</span>
              <Checkbox
                checked={draft.auth === "approval"}
                onCheckedChange={(value) =>
                  update("auth", value === true ? "approval" : "public")
                }
              />
            </label>
            <label className="flex items-center justify-between">
              <span>{t("settings_ext.publish")}</span>
              <Checkbox
                checked={draft.released}
                onCheckedChange={(value) => update("released", value === true)}
              />
            </label>
          </>
        )}
        {canShare && (
          <Button variant="outlined" onClick={() => setPermissionOpen(true)}>
            {t("managePermission", { ns: "permission" })}
          </Button>
        )}
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
      <div className="flex justify-end">
        <Button
          disabled={busy || !canEdit || !validSpaceSettings(draft, tagsTouched)}
          onClick={() => {
            void handleSave();
          }}
        >
          {t("confirm")}
        </Button>
      </div>
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
