import { Button, notification, toast } from "@bisheng/ui";
import {
  useQuery,
  useQueryClient,
  type QueryKey,
  type UseQueryResult,
} from "@tanstack/react-query";
import {
  useEffect,
  useCallback,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Dialog } from "@/components/bs-ui/dialog";
import { SpacePanelFrame } from "./SpacePanelFrame";
import { SpaceBasicFields, isValidSpaceBasic } from "./SpaceBasicFields";
import { SpaceSettingsSectionHeader } from "./SpaceSettingsControls";
import { validSpaceText } from "./spaceSettingsForm";
import { getModelListApi } from "@/controllers/API/finetune";
import {
  knowledgeSpaceApi,
  type KnowledgeSpaceApi,
} from "@/controllers/API/knowledgeSpace";
import {
  knowledgeQueryKeys,
  useCreateKnowledgeSpace,
  useKnowledgeCreationSettings,
  useKnowledgeSpaceInfo,
  type KnowledgeQueryScope,
} from "@/controllers/hooks/knowledge";
import { showApiError } from "@/controllers/request";
import { ModelSelect } from "../../ModelPage/manage/tabs/WorkbenchModel";
import {
  ProcessingDefaultsEditor,
  processingDefaultsToDraft,
  validateProcessingDefaultsDraft,
  type ProcessingDefaultsDraft,
} from "./ProcessingDefaultsEditor";

interface LibraryDialogProps {
  datalist: { id: string | number; name: string }[];
  scope: KnowledgeQueryScope;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onLoadEnd: () => void | Promise<void>;
  mode?: "create" | "edit";
  currentLib?: {
    id: string | number;
    name: string;
    description?: string;
    model?: string | number;
    create_time?: string;
  } | null;
  api?: KnowledgeSpaceApi;
}
interface ContentProps {
  scope: KnowledgeQueryScope;
  api: KnowledgeSpaceApi;
  onOpenChange: LibraryDialogProps["onOpenChange"];
  onLoadEnd: LibraryDialogProps["onLoadEnd"];
}
interface EmbeddingGroup {
  value: string;
  label: string;
  children: { value: string; label: string }[];
}
function positiveId(value: unknown): number | null {
  if (typeof value !== "string" || !/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && String(id) === value ? id : null;
}
export function embeddingGroups(raw: unknown): EmbeddingGroup[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((server) => {
    if (
      !server ||
      positiveId(String(server.id)) === null ||
      typeof server.name !== "string" ||
      !Array.isArray(server.models)
    )
      return [];
    const children = server.models.flatMap((model: Record<string, unknown>) =>
      model &&
      model.online === true &&
      model.model_type === "embedding" &&
      positiveId(String(model.id)) !== null &&
      typeof model.model_name === "string"
        ? [{ value: String(model.id), label: model.model_name }]
        : [],
    );
    return children.length
      ? [{ value: String(server.id), label: server.name, children }]
      : [];
  });
}

/** Fresh opening reads retire only after their final observer leaves. */
function useOpeningRead<T>(query: UseQueryResult<T>, key: QueryKey) {
  const client = useQueryClient();
  // The form remounts on scope/mode/resource changes; bind its opening key.
  const [stableKey] = useState(() => key);
  const current = useRef(false);
  const [value, setValue] = useState<T | null>(null);
  const refetch = query.refetch;
  const handleReload = useCallback(async () => {
    const result = await refetch({ cancelRefetch: false });
    if (current.current && result.isSuccess && result.data)
      setValue(result.data);
  }, [refetch]);
  useEffect(() => {
    current.current = true;
    void handleReload().catch((error) => {
      if (current.current) showApiError(error);
    });
    return () => {
      current.current = false;
      const retired = client
        .getQueryCache()
        .find({ queryKey: stableKey, exact: true });
      if (retired?.getObserversCount() === 0)
        void client.cancelQueries({ queryKey: stableKey, exact: true });
    };
  }, [client, stableKey, handleReload]);
  return { value, current, isError: query.isError, reload: handleReload };
}

interface FrameProps {
  title: string;
  busy?: boolean;
  onCancel: () => void;
  children: ReactNode;
  footer?: ReactNode;
  presentation?: "page";
  showPageNavigation?: boolean;
}
function FormFrame({
  title,
  busy = false,
  onCancel,
  children,
  footer,
  presentation,
  showPageNavigation = false,
}: FrameProps) {
  const { t } = useTranslation("knowledge");
  return (
    <SpacePanelFrame
      title={title}
      busy={busy}
      presentation={presentation}
      back={showPageNavigation ? { label: t("back"), onClick: onCancel } : undefined}
      footer={
        <>
          {(presentation !== "page" || showPageNavigation) && (
            <Button
              variant="outlined"
              color="default"
              disabled={busy}
              onClick={onCancel}
            >
              {t("cancel")}
            </Button>
          )}
          {footer}
        </>
      }
    >
      {children}
    </SpacePanelFrame>
  );
}
function reportError(error: unknown, scopeMessage: string) {
  const code =
    error && typeof error === "object" && "code" in error ? error.code : null;
  if (
    code === "knowledge_scope_changed" ||
    code === "knowledge_management_tenant_required"
  ) {
    notification.open({ type: "error", description: scopeMessage });
  } else showApiError(error);
}

interface CreateSpaceFormProps extends Pick<ContentProps, "scope" | "onLoadEnd"> {
  api?: KnowledgeSpaceApi;
  onCancel: () => void;
  onCreated?: () => void;
  presentation?: "page";
}

export function CreateSpaceForm({
  scope,
  api = knowledgeSpaceApi,
  onCancel,
  onCreated,
  onLoadEnd,
  presentation,
}: CreateSpaceFormProps) {
  const { t } = useTranslation("knowledge"),
    navigate = useNavigate();
  const bootstrap = useOpeningRead(
    useKnowledgeCreationSettings(scope, api),
    knowledgeQueryKeys.creation(scope),
  );
  const modelsKey = [
    ...knowledgeQueryKeys.scope(scope),
    "embedding-candidates",
  ];
  const models = useOpeningRead(
    useQuery({
      queryKey: modelsKey,
      queryFn: async () => embeddingGroups(await getModelListApi()),
      keepPreviousData: false,
    }),
    modelsKey,
  );
  const actions = useCreateKnowledgeSpace(scope, api);
  const [name, setName] = useState(""),
    [description, setDescription] = useState("");
  const [modelId, setModelId] = useState(""),
    [draft, setDraft] = useState<ProcessingDefaultsDraft | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (bootstrap.value) {
      setDraft(processingDefaultsToDraft(bootstrap.value.system_defaults));
      setModelId(bootstrap.value.embedding_model?.id ?? "");
    }
  }, [bootstrap.value]);
  const alive = () => bootstrap.current.current && models.current.current;
  const model = positiveId(modelId);
  const validModel =
    model !== null &&
    !!models.value?.some((group) =>
      group.children.some((option) => option.value === modelId),
    );
  const validation = draft ? validateProcessingDefaultsDraft(draft) : null;
  const validBasicFields = validSpaceText(name, description);
  const ready =
    bootstrap.value !== null && models.value !== null && draft !== null;
  const handleCreate = async (importing: boolean) => {
    if (
      busy ||
      !alive() ||
      !validBasicFields ||
      !validModel ||
      model === null ||
      !validation?.ok
    )
      return;
    setBusy(true);
    try {
      const result = await actions.createSpace({
        name,
        description,
        embedding_model_id: model,
        processing_defaults: validation.value,
      });
      if (!alive()) return;
      await onLoadEnd();
      if (!alive()) return;
      const destination = `${importing ? `/filelib/upload/${result.id}` : `/filelib/${result.id}`}${scope.view === "admin" ? "?view=admin" : ""}`;
      if (presentation === "page") navigate(destination, { replace: true });
      else navigate(destination);
      if (alive()) onCreated?.();
    } catch (error) {
      if (alive()) reportError(error, t("f118.scope_changed"));
    } finally {
      if (alive()) setBusy(false);
    }
  };
  const disabled =
    busy ||
    !ready ||
    !validBasicFields ||
    !validModel ||
    !validation?.ok;
  const page = presentation === "page";
  const basicFields = (
    <SpaceBasicFields
      name={name}
      description={description}
      onNameChange={setName}
      onDescriptionChange={setDescription}
      disabled={busy}
      compact={page}
      mode="create"
    />
  );
  const advancedFields = ready && (
    <>
      <fieldset
        disabled={busy}
        className={page ? "min-w-0 [&_.bisheng-label]:mb-2 [&_.bisheng-label]:text-body [&_.bisheng-label]:text-text-1" : undefined}
      >
        <ModelSelect
          label={t("f118.embedding_model")}
          close
          value={modelId}
          options={models.value}
          onChange={(value: string) => {
            if (!busy) setModelId(value);
          }}
        />
      </fieldset>
      {!validModel && (
        <p role="alert" className="text-sm text-red-500">
          {t("f118.invalid_embedding_model")}{" "}
          {bootstrap.value?.embedding_model?.name}
        </p>
      )}
      {!page && <h3 className="text-sm font-medium">{t("f118.advanced_settings")}</h3>}
      <p className={page ? "text-body text-text-3" : "text-sm text-text-2"}>
        {t("f118.future_uploads_only")}
      </p>
      <ProcessingDefaultsEditor
        value={draft}
        onChange={setDraft}
        disabled={busy}
        compact={page}
      />
    </>
  );
  return (
    <FormFrame
      title={t("f118.create_space")}
      busy={busy}
      onCancel={onCancel}
      presentation={presentation}
      showPageNavigation={page}
      footer={
        <>
          <Button
            variant="outlined"
            color="default"
            disabled={disabled}
            onClick={() => {
              void handleCreate(false);
            }}
          >
            {t("finishCreate")}
          </Button>
          <Button
            disabled={disabled}
            onClick={() => {
              void handleCreate(true);
            }}
          >
            {t("createImport", { ns: "bs" })}
          </Button>
        </>
      }
    >
      {ready ? (
        page ? (
          <div className="space-y-6">
            <section className="space-y-6">
              <SpaceSettingsSectionHeader kind="basic" title={t("settings_ext.basic")} />
              <div className="px-6 max-[768px]:px-0">{basicFields}</div>
            </section>
            <section className="space-y-6">
              <SpaceSettingsSectionHeader kind="advanced" title={t("f118.advanced_settings")} />
              <div className="min-w-0 space-y-4 px-6 max-[768px]:px-0">{advancedFields}</div>
            </section>
          </div>
        ) : (
          <div className="space-y-4">{basicFields}{advancedFields}</div>
        )
      ) : bootstrap.isError || models.isError ? (
        <div role="alert">
          <p>{t("f118.load_failed")}</p>
          <Button
            onClick={() => {
              void Promise.all([bootstrap.reload(), models.reload()]).catch(
                (error) => {
                  if (alive()) reportError(error, t("f118.scope_changed"));
                },
              );
            }}
          >
            {t("retry")}
          </Button>
        </div>
      ) : (
        <p role="status">{t("f118.loading_space")}</p>
      )}
    </FormFrame>
  );
}

function EditSpaceForm({
  scope,
  api,
  onOpenChange,
  onLoadEnd,
  spaceId,
  presentation,
}: ContentProps & { spaceId: number; presentation?: "page" }) {
  const { t } = useTranslation("knowledge"),
    client = useQueryClient();
  const read = useOpeningRead(
    useKnowledgeSpaceInfo(scope, spaceId, api),
    knowledgeQueryKeys.info(scope, spaceId),
  );
  const [name, setName] = useState(""),
    [description, setDescription] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    if (read.value) {
      setName(read.value.name);
      setDescription(read.value.description ?? "");
    }
  }, [read.value]);
  const originalPublication = read.value?.is_released;
  const handleSave = async () => {
    if (
      busy ||
      !read.current.current ||
      !isValidSpaceBasic(name, description) ||
      typeof originalPublication !== "boolean"
    )
      return;
    setBusy(true);
    try {
      await api.updateSpaceBasicInfo(spaceId, {
        name,
        description,
        is_released: originalPublication,
      });
      if (!read.current.current) return;
      await Promise.all([
        client.invalidateQueries({
          queryKey: knowledgeQueryKeys.info(scope, spaceId),
        }),
        client.invalidateQueries({
          queryKey: knowledgeQueryKeys.visible(scope),
        }),
        client.invalidateQueries({
          queryKey: [...knowledgeQueryKeys.scope(scope), "admin-list"],
        }),
      ]);
      if (!read.current.current) return;
      await onLoadEnd();
      if (read.current.current) {
        if (presentation === "page")
          toast.show({ type: "success", message: t("detail.saved") });
        else onOpenChange(false);
      }
    } catch (error) {
      if (read.current.current) reportError(error, t("f118.scope_changed"));
    } finally {
      if (read.current.current) setBusy(false);
    }
  };
  return (
    <FormFrame
      title={t("f118.edit_space")}
      presentation={presentation}
      busy={busy}
      onCancel={() => onOpenChange(false)}
      footer={
        <Button
          disabled={
            busy ||
            !read.value ||
            !isValidSpaceBasic(name, description) ||
            typeof originalPublication !== "boolean"
          }
          onClick={() => {
            void handleSave();
          }}
        >
          {t("confirm")}
        </Button>
      }
    >
      {read.value ? (
        <SpaceBasicFields
          name={name}
          description={description}
          onNameChange={setName}
          onDescriptionChange={setDescription}
          disabled={busy}
        />
      ) : read.isError ? (
        <div role="alert">
          <p>{t("f118.load_failed")}</p>
          <Button
            onClick={() => {
              void read.reload().catch((error) => {
                if (read.current.current)
                  reportError(error, t("f118.scope_changed"));
              });
            }}
          >
            {t("retry")}
          </Button>
        </div>
      ) : (
        <p role="status">{t("f118.loading_space")}</p>
      )}
    </FormFrame>
  );
}

export function KnowledgeLibraryDialog({
  scope,
  open,
  onOpenChange,
  onLoadEnd,
  mode = "create",
  currentLib = null,
  api = knowledgeSpaceApi,
}: LibraryDialogProps) {
  const { t } = useTranslation("knowledge");
  const tenant =
    scope && Number.isSafeInteger(scope.tenantId) && scope.tenantId > 0;
  const spaceId = currentLib ? positiveId(String(currentLib.id)) : null;
  const ready =
    tenant &&
    !!scope.identityKey &&
    (mode === "edit"
      ? spaceId !== null
      : scope.managementTenantId === scope.tenantId);
  const key = JSON.stringify([
    scope?.identityKey,
    scope?.tenantId,
    scope?.managementTenantId,
    scope?.view,
    mode,
    spaceId,
  ]);
  const props = { scope, api, onOpenChange, onLoadEnd };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open &&
        (ready ? (
          mode === "create" ? (
            <CreateSpaceForm
              key={key}
              scope={scope}
              api={api}
              onCancel={() => onOpenChange(false)}
              onCreated={() => onOpenChange(false)}
              onLoadEnd={onLoadEnd}
            />
          ) : (
            <EditSpaceForm key={key} {...props} spaceId={spaceId!} />
          )
        ) : (
          <FormFrame
            title={t(
              mode === "create" ? "f118.create_space" : "f118.edit_space",
            )}
            onCancel={() => onOpenChange(false)}
          >
            <p role="alert">{t("f118.scope_unavailable")}</p>
          </FormFrame>
        ))}
    </Dialog>
  );
}
