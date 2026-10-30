import { asrHintKey, speechModelTypes } from "./speechConfig";
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@bisheng/ui";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@bisheng/ui";
import { Label } from "@/components/bs-ui/label";
import { Select } from "@bisheng/ui";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { Switch } from "@bisheng/ui";
import { ModelFieldHint as QuestionTooltip } from "./ModelFieldHint";
import { ModelType } from "@/controllers/API/modelDiscovery";
import { ChevronDown, ChevronUp, Settings, Trash2Icon } from "lucide-react";
import { ChangeEvent, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { availableModelTypes } from "./modelDiscoveryState";

import {
  ModelItemConfig,
  advancedParamsPlaceholder,
  advancedParamsText,
  parseAdvancedParams,
  withAdvancedParams,
} from "./modelAdvancedParams";

interface ModelItemProps {
  data: {
    name: string;
    model_name: string;
    model_type: ModelType;
    config?: ModelItemConfig;
  };
  type: string;
  onDelete: () => void;
  onInput: (name: string, type: ModelType) => unknown;
  onConfig: (config: ModelItemConfig) => void;
}

export function ModelItem({
  data,
  type,
  onDelete,
  onInput,
  onConfig,
}: ModelItemProps) {
  const { t } = useTranslation(["bs", "model"]);
  const selectLabels = useSelectLabels();
  const { t: tModel } = useTranslation("model");
  const controlId = useId();
  const [expanded, setExpanded] = useState(!data.model_name);
  const [model, setModel] = useState({
    ...data,
    voice: data.config?.voice || "",
  });
  const [error, setError] = useState("");
  const [isWebSearchEnabled, setIsWebSearchEnabled] = useState(
    data.config?.enable_web_search || false,
  );
  const [voiceError, setVoiceError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [inputAdvancedParams, setInputAdvancedParams] = useState("");
  const [savedInputParams, setSavedInputParams] = useState(
    advancedParamsText(data.config, type, data.model_type),
  );
  const [advancedParams, setAdvancedParams] = useState(() =>
    advancedParamsPlaceholder(type, data.model_type),
  );
  const [jsonError, setJsonError] = useState(false);

  useEffect(() => {
    setModel({ ...data, voice: data.config?.voice || "" });
    setIsWebSearchEnabled(data.config?.enable_web_search || false);
    const userSavedParams = advancedParamsText(
      data.config,
      type,
      data.model_type,
    );
    setSavedInputParams(userSavedParams);
    setAdvancedParams(advancedParamsPlaceholder(type, data.model_type));
    if (dialogOpen) setInputAdvancedParams(userSavedParams);
    setJsonError(false);
  }, [data, dialogOpen, type]);

  const handleInput = (e: ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    const updatedModel = { ...model, model_name: value };
    setModel(updatedModel);
    const repeated = onInput(value, model.model_type);

    setError("");
    if (!value) setError(t("model.modelNameEmpty"));
    if (value.length > 100) setError(t("model.modelNameLength"));
    if (repeated) setError(t("model.modelNameDuplicate"));
  };

  const handleVoiceInput = (e: ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    const updatedModel = { ...model, voice: value };
    setModel(updatedModel);
    onConfig({ ...model.config, voice: value });
    setVoiceError("");
  };

  const handleSelectChange = (val: ModelType) => {
    const updatedModel = { ...model, model_type: val };
    setModel(updatedModel);
    onInput(model.model_name, val);
  };

  const handleDelClick = () => {
    bsConfirm({
      desc: t("model.deleteModelConfirmation"),
      onOk(next) {
        onDelete();
        next();
      },
    });
  };

  const handleSwitchChange = (checked: boolean) => {
    setIsWebSearchEnabled(checked);
    onConfig({
      ...model.config,
      enable_web_search: checked,
    });
  };

  const handleSaveAdvancedParams = () => {
    let config: ReturnType<typeof withAdvancedParams>;
    try {
      config = withAdvancedParams(
        model.config,
        inputAdvancedParams,
        model.model_type,
      );
    } catch {
      setJsonError(true);
      return;
    }
    onConfig(config);
    setSavedInputParams(config.user_kwargs || "");
    setInputAdvancedParams(config.user_kwargs || "");
    setDialogOpen(false);
    setJsonError(false);
  };

  const handleCloseDialog = () => {
    setInputAdvancedParams(savedInputParams);
    setJsonError(false);
    setDialogOpen(false);
  };

  const needsConfiguration =
    !model.model_name.trim() ||
    model.model_name.length > 100 ||
    (model.model_type === "tts" && !model.voice.trim());
  const hasParameters = Object.values(model.config || {}).some(
    (value) => value !== undefined && value !== "" && value !== false,
  );

  return (
    <div className="group w-full">
      <div className="flex items-center gap-3 px-3 py-2.5">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium" title={model.model_name}>
            {model.model_name || tModel("model.unnamedModel")}
          </p>
          <p
            className={`mt-0.5 text-xs ${needsConfiguration || error ? "text-amber-600" : "text-muted-foreground"}`}
          >
            {error ||
              tModel(
                needsConfiguration
                  ? "model.configurationRequired"
                  : hasParameters
                    ? "model.parametersConfigured"
                    : "model.defaultParameters",
              )}
          </p>
        </div>
        <span className="shrink-0 rounded bg-muted px-2 py-1 text-xs text-muted-foreground">
          {tModel(`model.type_${model.model_type}`)}
        </span>
        <Button
          size="small"
          variant="text"
          color="default"
          aria-expanded={expanded}
          aria-controls={controlId}
          onClick={() => setExpanded((previous) => !previous)}
        >
          {expanded ? (
            <ChevronUp className="mr-1 size-4" />
          ) : (
            <ChevronDown className="mr-1 size-4" />
          )}
          {tModel(
            expanded ? "model.collapseConfiguration" : "model.configureModel",
          )}
        </Button>
        <Button
          size="small"
          iconOnly
          variant="text"
          color="default"
          aria-label={tModel("model.removeConfiguredModel", {
            name: model.model_name || model.name,
          })}
          onClick={handleDelClick}
        >
          <Trash2Icon className="size-4 text-muted-foreground" />
        </Button>
      </div>
      {expanded && (
        <div id={controlId} className="space-y-3 border-t bg-muted/20 p-3">
          <div className="flex flex-wrap items-start gap-3">
            <div className="min-w-0 flex-[1_1_16rem] space-y-2">
              <Label
                htmlFor={`${controlId}-name`}
                className="bisheng-label flex h-8 items-center"
              >
                <span>{t("model.modelName")}</span>
                <QuestionTooltip
                  className="ml-1"
                  content={t("model.modelNameTooltip")}
                />
              </Label>
              <Input
                id={`${controlId}-name`}
                value={model.model_name}
                onChange={handleInput}
                className="h-8"
              ></Input>
              {asrHintKey(type, model.model_type) && (
                <p className="text-xs text-muted-foreground">
                  {t(asrHintKey(type, model.model_type)!)}
                </p>
              )}
              {error && <span className="text-red-500 text-xs">{error}</span>}
            </div>
            <div className="w-full shrink-0 space-y-2 sm:w-40">
              <Label
                htmlFor={`${controlId}-type`}
                className="bisheng-label flex h-8 items-center"
              >
                {t("model.modelType")}
              </Label>
              <Select
                {...selectLabels}
                id={`${controlId}-type`}
                aria-label={t("model.modelType")}
                value={model.model_type}
                onChange={(value) => {
                  if (value) handleSelectChange(value as ModelType);
                }}
                options={Array.from(
                  new Set([
                    ...availableModelTypes(type),
                    ...speechModelTypes(type),
                    // Keep the option on existing rerank rows so their current value still renders.
                    ...(model.model_type === "rerank" ? ["rerank"] : []),
                  ]),
                ).map((value) => ({
                  value,
                  label: tModel(`model.type_${value}`),
                }))}
              />
            </div>
            <div className="ml-auto grid min-h-8 w-96 max-w-full shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-6 self-end">
              <div className="flex min-h-8 items-center">
                {model.model_type === "llm" &&
                  ["qwen", "tencent", "moonshot", "minimax"].includes(type) && (
                    <div className="flex min-w-0 items-center gap-2">
                      <Label
                        htmlFor={`${controlId}-search`}
                        className="text-xs text-muted-foreground"
                      >
                        {t("model.webSearch")}
                      </Label>
                      <QuestionTooltip
                        className="shrink-0"
                        content={t(
                          `model.webSearchTip${{ qwen: "Qwen", tencent: "Tencent", moonshot: "Moonshot", minimax: "Minimax" }[type]}`,
                        )}
                      />
                      <Switch
                        id={`${controlId}-search`}
                        className="shrink-0"
                        checked={isWebSearchEnabled}
                        onCheckedChange={handleSwitchChange}
                      />
                    </div>
                  )}
              </div>
              <div className="min-w-0">
                {(model.model_type === "llm" ||
                  model.model_type === "embedding") && (
                  <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
                    <DialogTrigger asChild>
                      <button
                        type="button"
                        aria-label={t("model.advancedParamsConfig")}
                        className="flex min-h-8 items-center gap-1 whitespace-nowrap text-left text-primary text-xs"
                      >
                        <Settings
                          size={16}
                          strokeWidth={2}
                          className="shrink-0"
                        />
                        <span>{t("model.advancedParamsConfig")}</span>
                      </button>
                    </DialogTrigger>

                    <DialogContent className="sm:max-w-[625px]">
                      <DialogHeader>
                        <DialogTitle>
                          {t("model.advancedParamsConfig")}
                        </DialogTitle>
                      </DialogHeader>
                      <div className="mt-4 text-gray-500">
                        {model.model_type === "llm" && (
                          <p className="mb-3 text-xs text-muted-foreground">
                            {tModel(
                              type === "ollama"
                                ? "model.advancedContextHint"
                                : "model.advancedTokenHint",
                            )}
                          </p>
                        )}
                        <div className="flex items-center justify-between gap-4">
                          <Label>{t("model.pasteAdvancedParamsHere")}</Label>
                          <Button
                            variant="link"
                            size="small"
                            className="h-auto shrink-0 px-0"
                            onClick={() => {
                              setInputAdvancedParams(advancedParams);
                              setJsonError(false);
                            }}
                          >
                            {t("model.insertParamsExample")}
                          </Button>
                        </div>
                        <Textarea
                          value={inputAdvancedParams}
                          onChange={(event) => {
                            setInputAdvancedParams(event.target.value);
                            try {
                              parseAdvancedParams(event.target.value);
                              setJsonError(false);
                            } catch {
                              setJsonError(true);
                            }
                          }}
                          textareaClassName={`mt-1 font-mono text-sm ${jsonError ? "border-red-500 focus-visible:ring-red-500" : ""}`}
                          rows={10}
                          placeholder={advancedParams}
                        />
                        {jsonError && (
                          <span className="text-red-500 text-xs mt-1 inline-block">
                            {t("model.errorInvalidJsonFormat")}
                          </span>
                        )}
                      </div>
                      <DialogFooter className="mt-4">
                        <Button
                          variant="outlined"
                          color="default"
                          onClick={handleCloseDialog}
                        >
                          {t("model.cancel")}
                        </Button>
                        <Button onClick={handleSaveAdvancedParams}>
                          {t("model.save")}
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                )}
              </div>
            </div>
          </div>
          {model.model_type === "tts" && (
            <div className="sm:max-w-sm">
              <Label className="bisheng-label">
                <span>{t("model.voiceType")}</span>
                <span className="text-red-500">*</span>
                <QuestionTooltip
                  className="relative top-0.5 ml-1"
                  content={t("model.voiceTypeTooltip")}
                />
              </Label>
              <Input
                value={model.voice || ""}
                onChange={handleVoiceInput}
                className="h-8"
              ></Input>

              {voiceError && (
                <span className="text-red-500 text-xs">{voiceError}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
