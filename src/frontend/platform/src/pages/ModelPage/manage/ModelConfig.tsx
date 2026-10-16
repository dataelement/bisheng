// @ts-strict-ignore
import { LoadingIcon } from "@/components/bs-icons/loading";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button, LoadButton } from "@/components/bs-ui/button";
import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select";
import { Switch } from "@/components/bs-ui/switch";
import { useToast } from "@/components/bs-ui/toast/use-toast";
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { generateUUID } from "@/components/bs-ui/utils";
import ShadTooltip from "@/components/ShadTooltipComponent";
import { locationContext } from "@/contexts/locationContext";
import { userContext } from "@/contexts/userContext";
import {
  addLLmServer,
  deleteLLmServer,
  getLLmServerDetail,
  updateLLmServer,
} from "@/controllers/API/finetune";
import { captureAndAlertRequestErrorHoc } from "@/controllers/request";
import { useAdminScope } from "@/hooks/useAdminScope";
import { ArrowLeft, Plus } from "lucide-react";
import { useContext, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import CustomForm from "./CustomForm";
import { ModelDiscovery } from "./ModelDiscovery";
import { ModelItem } from "./ModelItem";
import { hasDuplicateModelName, hasInvalidModelName, trimModelNames } from "./modelNameTrim";
import { canShareToChildren, isGlobalSuperUser } from "./permissions";
import { useLinsightConfig } from "./tabs/WorkbenchModel";
import { useModelProviderInfo } from "./useLink";

export const modelProvider = [
  { name: "OpenAI", value: "openai" },
  { name: "Azure OpenAI", value: "azure_openai" },
  { name: "Ollama", value: "ollama" },
  { name: "xinference", value: "xinference" },
  { name: "llamacpp", value: "llamacpp" },
  { name: "vllm", value: "vllm" },
  { name: "model.provider_qwen", value: "qwen" },
  { name: "DeepSeek", value: "deepseek" },
  { name: "model.provider_silicon", value: "silicon" },
  { name: "model.provider_volcengine", value: "volcengine" },
  { name: "model.provider_zhipu", value: "zhipu" },
  { name: "model.provider_spark", value: "spark" },
  { name: "model.provider_tencent", value: "tencent" },
  { name: "model.provider_moonshot", value: "moonshot" },
  { name: "model.provider_qianfan", value: "qianfan" },
  { name: "Minimax", value: "minimax" },
  { name: "Anthropic", value: "anthropic" },
  { name: "MindIE", value: "MindIE" },
];
const bishengModelProvider = { name: "bishengRT", value: "bisheng_rt" };

const defaultForm = {
  id: null as any,
  type: "",
  name: "",
  limit_flag: false,
  limit: 1,
  config: {},
  models: [],
  // Root-only switch; default true to match backend LLMServerCreateReq
  // default and v2.5.1 decision-2 ("default share, opt-out via UI").
  share_to_children: true,
  // Echoed by the backend so we can hide the toggle on Root servers
  // viewed under a Child scope (those rows are read-only anyway).
  is_root_shared_readonly: false,
  tenant_id: undefined,
};

export default function ModelConfig({
  id,
  onGetName,
  onBack,
  onReload,
  onBerforSave,
  onAfterSave,
}) {
  const { t } = useTranslation(["bs", "model"]);
  const { refetch: refetchConfig } = useLinsightConfig();
  const { user } = useContext(userContext);
  const { appConfig } = useContext(locationContext);

  const [formData, setFormData] = useState({ ...defaultForm });
  const [connectionVersion, setConnectionVersion] = useState(0);
  const [autoFetchVersion, setAutoFetchVersion] = useState(0);

  // Create mode reads the admin scope fresh instead of taking it from the
  // list page: the scope is a server-side lease that can expire while the
  // user sits on the list, and only the value at open time matches the
  // tenant the backend will write on save.
  const isCreate = id === -1;
  const { scope: adminScope } = useAdminScope({
    enabled:
      appConfig.multiTenantEnabled && isGlobalSuperUser(user) && isCreate,
  });
  const showShareToggle = canShareToChildren({
    multiTenantEnabled: appConfig.multiTenantEnabled,
    user,
    isCreate,
    serverTenantId: formData.tenant_id,
    scopeTenantId: adminScope.scope_tenant_id,
  });

  useEffect(() => {
    if (id === -1) return;
    getLLmServerDetail(id).then((res) => {
      setFormData(res);
    });
  }, [id]);

  const handleTypeChange = (val) => {
    const name = onGetName(
      _modelProvider.find((el) => el.value === val).name || "",
    );
    const models = [];
    setFormData({ ...formData, type: val, name, config: {}, models });
  };

  const handleAddModel = () => {
    const maxIndex = formData.models.reduce(
      (max, el, i) =>
        el.name.match(/model (\d+)/)
          ? Math.max(max, +el.name.match(/model (\d+)/)[1])
          : max,
      0,
    );

    const model = {
      id: generateUUID(32),
      name: `model ${maxIndex + 1}`,
      model_name: "",
      model_type: "llm",
      voice: "",
    };
    const newModels = [...formData.models, model];
    setFormData({ ...formData, models: newModels });
  };

  const handleDelete = (index) => {
    const models = formData.models.filter((el, i) => index !== i);
    setFormData({ ...formData, models });
  };

  const handleModelChange = (name, type, index) => {
    const models = formData.models.map((el, i) =>
      index === i
        ? {
            ...el,
            config: type === el.model_type ? el.config : {},
            model_name: name,
            model_type: type,
            voice: type === "tts" ? el.voice || "" : "",
          }
        : el,
    );
    setFormData({ ...formData, models });

    return formData.models.find(
      (el, i) => index !== i && el.model_name === name,
    );
  };

  const handleModelConfig = (config, index) => {
    const models = formData.models.map((el, i) =>
      index === i
        ? {
            ...el,
            config,
          }
        : el,
    );
    setFormData({ ...formData, models });
  };

  const { message } = useToast();
  const formRef = useRef(null);
  const [isLoading, setIsLoading] = useState(false);
  const handleSave = async () => {
    setIsLoading(true);
    try {
      const exists = onBerforSave(formData.id, formData.name);
      if (exists) {
        return message({
          variant: "warning",
          description: t("model.duplicateServiceProviderName"),
        });
      }
      if (!formData.name || formData.name.length > 100) {
        return message({
          variant: "warning",
          description: t("model.duplicateServiceProviderNameValidation"),
        });
      }
      const [config, errorKey] = formRef.current.getData();
      if (errorKey) {
        return message({
          variant: "warning",
          description: `${errorKey} ${t("model.notBeEmpty")}`,
        });
      }

      const normalizedModels = trimModelNames(formData.models);
      setFormData({ ...formData, models: normalizedModels });
      const hasTTSVoiceError = normalizedModels.some(
        (model) => model.model_type === "tts" && !model.config?.voice,
      );
      if (hasInvalidModelName(normalizedModels) || normalizedModels.some((model) => !model.model_type)) {
        return message({
          variant: "warning",
          description: t("model.modelNameValidation"),
        });
      }
      if (hasDuplicateModelName(normalizedModels)) {
        return message({
          variant: "warning",
          description: t("model.modelDuplicate"),
        });
      }
      if (hasTTSVoiceError) {
        return message({
          variant: "warning",
          description: t("model.voiceTypeRequired"),
        });
      }

      const saveData = {
        ...formData,
        models: normalizedModels,
        config,
      };

      if (id === -1) {
        await captureAndAlertRequestErrorHoc(
          addLLmServer(saveData).then((res) => {
            onAfterSave(res.code === 10803 ? res.msg : t("model.addSuccess"));
            onBack();
          }),
        );
      } else {
        await captureAndAlertRequestErrorHoc(
          updateLLmServer(saveData).then((res) => {
            onAfterSave(t("model.updateSuccess"));
            onBack();
          }),
        );
      }
      refetchConfig();
    } catch (error) {
      console.error("Save error:", error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleModelDel = () => {
    bsConfirm({
      desc: t("model.deleteConfirmation"),
      onOk(next) {
        captureAndAlertRequestErrorHoc(
          deleteLLmServer(id).then((res) => {
            onAfterSave(t("model.deleteSuccess"));
            refetchConfig();
          }),
        );
        onBack();
        next();
      },
    });
  };

  const _modelProvider = useMemo(() => {
    return (
      id === -1 ? modelProvider : [...modelProvider, bishengModelProvider]
    ).map((provider) => ({
      ...provider,
      name: provider.name.startsWith("model.")
        ? t(provider.name, { ns: "model" })
        : provider.name,
    }));
  }, [id, t]);

  const providerInfo = useModelProviderInfo(formData.type);

  if (!formData)
    return (
      <div className="absolute left-0 top-0 z-10 flex h-full w-full items-center justify-center bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <LoadingIcon />
      </div>
    );

  return (
    <div className="relative size-full py-4">
      <div className="flex ml-6 items-center gap-x-3">
        <ShadTooltip content={t("back", { ns: "bs" })} side="right">
          <button
            className="extra-side-bar-buttons w-[36px]"
            onClick={() => onBack()}
          >
            <ArrowLeft strokeWidth={1.5} className="side-bar-button-size" />
          </button>
        </ShadTooltip>
        <span>
          {id === -1 ? t("model.addModel") : t("model.modelConfiguration")}
        </span>
      </div>
      <div className="w-full max-w-4xl min-w-64 px-4 pb-10 mx-auto mt-6 h-[calc(100vh-220px-var(--license-banner-h,0px))] overflow-y-auto">
        <h3 className="mb-3 text-sm font-medium">
          {t("model.connectionSettings", { ns: "model" })}
        </h3>
        <div className="mb-2">
          <Label className="bisheng-label">
            {" "}
            {t("model.interModelFormat")}
          </Label>
          <Select
            value={formData.type}
            disabled={id !== -1}
            onValueChange={handleTypeChange}
          >
            <SelectTrigger>
              <SelectValue placeholder="" />
            </SelectTrigger>
            <SelectContent>
              <SelectGroup>
                {_modelProvider.map((model) => (
                  <SelectItem key={model.value} value={model.value}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <div className="mb-2">
          <Label className="bisheng-label">
            <span>{t("model.serviceProviderName")}</span>
            <QuestionTooltip
              className="relative top-0.5 ml-1"
              content={t("model.serviceProviderNameTooltip")}
            >
              <span />
            </QuestionTooltip>
          </Label>
          <Input
            value={formData.name}
            onChange={(e) => {
              const name = e.target.value;
              setFormData({ ...formData, name });
              document.getElementById(
                "model_provider_name_error",
              ).style.display = !name || name.length > 100 ? "block" : "none";
            }}
          ></Input>
          <span
            id="model_provider_name_error"
            style={{ display: "none" }}
            className="text-red-500 text-xs"
          >
            {formData.name
              ? t("model.max100Characters")
              : t("model.cannotBeEmpty")}
          </span>
        </div>
        <CustomForm
          ref={formRef}
          showDefault={id === -1}
          provider={formData.type}
          formData={formData.config}
          providerName={
            _modelProvider.find((el) => el.value === formData.type)?.name
          }
          apiKeySite={providerInfo?.apiKeyUrl}
          onConnectionChange={() =>
            setConnectionVersion((version) => version + 1)
          }
          onConnectionBlur={() => {
            const [, errorKey] = formRef.current.getData();
            if (!errorKey) setAutoFetchVersion((version) => version + 1);
          }}
        />
        <div className={formData.type ? "visible" : "invisible"}>
          <section className="mt-6 space-y-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div>
                <h3 className="text-sm font-medium">
                  {t("model.configuredModels", {
                    ns: "model",
                    count: formData.models.length,
                  })}
                </h3>
                <p className="mt-1 text-xs text-muted-foreground">
                  {t("model.configuredModelsHint", { ns: "model" })}
                </p>
              </div>
              <div className="flex gap-2">
                <ModelDiscovery
                  provider={formData.type}
                  connectionVersion={connectionVersion}
                  autoFetchVersion={autoFetchVersion}
                  existing={formData.models.map((model) =>
                    model.model_name.trim(),
                  )}
                  getConnection={() => {
                    const [config, errorKey] = formRef.current.getData();
                    if (errorKey) {
                      message({
                        variant: "warning",
                        description: `${errorKey} ${t("model.notBeEmpty")}`,
                      });
                      return null;
                    }
                    return {
                      provider: formData.type,
                      config,
                      ...(id !== -1 ? { server_id: id } : {}),
                    };
                  }}
                  onImport={(catalog) =>
                    setFormData((previous) => {
                      const names = new Set(
                        previous.models.map((model) => model.model_name.trim()),
                      );
                      const models = catalog
                        .filter((model) => !names.has(model.model_name))
                        .map((model) => ({
                          id: generateUUID(32),
                          name: model.display_name,
                          model_name: model.model_name,
                          model_type: model.model_type,
                          config: {},
                          voice: "",
                        }));
                      return {
                        ...previous,
                        models: [...previous.models, ...models],
                      };
                    })
                  }
                />
                <Button size="sm" variant="ghost" onClick={handleAddModel}>
                  <Plus className="mr-1 size-4" />
                  {t("model.addModelManually", { ns: "model" })}
                </Button>
              </div>
            </div>
            {formData.models.length > 0 ? (
              <div className="rounded-md border divide-y">
                {formData.models.map((m, i) => (
                  <ModelItem
                    key={m.id}
                    data={m}
                    type={formData.type}
                    onInput={(name, type) => handleModelChange(name, type, i)}
                    onConfig={(config) => handleModelConfig(config, i)}
                    onDelete={() => handleDelete(i)}
                  />
                ))}
              </div>
            ) : (
              <div className="rounded-md border border-dashed px-4 py-8 text-center text-sm text-muted-foreground">
                {t("model.noConfiguredModels", { ns: "model" })}
              </div>
            )}
            {providerInfo && (
              <a
                href={providerInfo.modelUrl}
                target="_blank"
                rel="noreferrer"
                className="inline-block text-xs text-primary"
              >
                {t("model.visitOfficialWebsiteToViewAvailableModels")}
              </a>
            )}
          </section>
          <section className="mt-6 border-t pt-4">
            <h3 className="mb-3 text-sm font-medium">
              {t("model.serviceSettings", { ns: "model" })}
            </h3>
            <div className="mb-2">
              <div className="flex items-center gap-x-6">
                <Label className="bisheng-label">
                  {t("model.dailyCallLimit")}
                </Label>
                <Switch
                  checked={formData.limit_flag}
                  onCheckedChange={(val) =>
                    setFormData((form) => ({ ...form, limit_flag: val }))
                  }
                />
                <div
                  className={`flex items-center gap-x-2 ${formData.limit_flag ? "" : "invisible"}`}
                >
                  <Input
                    type="number"
                    value={formData.limit}
                    onChange={(e) =>
                      setFormData({
                        ...formData,
                        limit: Number(e.target.value),
                      })
                    }
                    className="w-24 h-8"
                  ></Input>
                  <span>{t("model.timesPerDay")}</span>
                </div>
              </div>
            </div>
            {showShareToggle && (
              <div className="mb-2">
                <div className="flex items-center gap-x-6">
                  <Label className="bisheng-label">
                    {t("model.shareToChildren")}
                  </Label>
                  <Switch
                    checked={formData.share_to_children}
                    onCheckedChange={(val) =>
                      setFormData((form) => ({
                        ...form,
                        share_to_children: val,
                      }))
                    }
                  />
                </div>
              </div>
            )}
          </section>
        </div>
      </div>
      <div className="absolute right-0 bottom-0 p-4 flex gap-4">
        {id !== -1 && (
          <Button
            className="px-8"
            variant="destructive"
            onClick={handleModelDel}
          >
            {t("model.delete")}
          </Button>
        )}
        <Button className="px-8" variant="outline" onClick={() => onBack()}>
          {t("model.cancel")}
        </Button>
        <LoadButton
          className="px-16"
          disabled={!formData.type}
          loading={isLoading}
          onClick={handleSave}
        >
          {isLoading ? t("model.modelStatusChecking") : t("model.save")}
        </LoadButton>
      </div>
    </div>
  );
}
