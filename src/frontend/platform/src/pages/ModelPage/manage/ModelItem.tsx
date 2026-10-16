import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";
import { Button } from "@/components/bs-ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/bs-ui/dialog";
import { Input, Textarea } from "@/components/bs-ui/input";
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
import { QuestionTooltip } from "@/components/bs-ui/tooltip";
import { ModelType } from "@/controllers/API/modelDiscovery";
import {
  ChevronDown,
  ChevronUp,
  Settings,
  Trash2Icon,
} from "lucide-react";
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
          size="sm"
          variant="ghost"
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
          size="icon"
          variant="ghost"
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
            <div className="min-w-0 flex-[1_1_16rem]">
              <Label htmlFor={`${controlId}-name`} className="bisheng-label">
                <span>{t("model.modelName")}</span>
                <QuestionTooltip
                  className="relative top-0.5 ml-1"
                  content={t("model.modelNameTooltip")}
                />
              </Label>
              <Input
                id={`${controlId}-name`}
                value={model.model_name}
                onChange={handleInput}
                className="h-8"
              ></Input>
              {error && <span className="text-red-500 text-xs">{error}</span>}
            </div>
            <div className="w-full shrink-0 sm:w-40">
              <Label htmlFor={`${controlId}-type`} className="bisheng-label">
                {t("model.modelType")}
              </Label>
              <Select
                value={model.model_type}
                onValueChange={(value) => handleSelectChange(value as ModelType)}
              >
                <SelectTrigger id={`${controlId}-type`} className="h-8">
                  <SelectValue placeholder="" />
                </SelectTrigger>
                <SelectContent>
                  <SelectGroup>
                    {availableModelTypes(type).map((value) => (
                      <SelectItem key={value} value={value}>
                        {tModel(`model.type_${value}`)}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                </SelectContent>
              </Select>
            </div>
            <div className="grid min-h-8 w-80 max-w-full shrink-0 grid-cols-[9rem_minmax(0,1fr)] items-center gap-4 self-end">
              <div className="flex min-h-8 items-center">
                {model.model_type === "llm" &&
                  ["qwen", "tencent", "moonshot"].includes(type) && (
                    <div className="flex shrink-0 items-center gap-2">
                      <Label
                        htmlFor={`${controlId}-search`}
                        className="text-xs text-muted-foreground whitespace-nowrap"
                      >
                        {t("model.webSearch")}
                      </Label>
                      <QuestionTooltip
                        className="shrink-0"
                        content={tModel("model.webSearchHint")}
                      />
                      <Switch
                        id={`${controlId}-search`}
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
                        className="flex min-h-8 items-center gap-1 text-left text-primary text-xs"
                      >
                        <Settings size={16} strokeWidth={2} className="shrink-0" />
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
                        <Label>{t("model.pasteAdvancedParamsHere")}</Label>
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
                          className={`mt-1 font-mono text-sm ${jsonError ? "border-red-500 focus-visible:ring-red-500" : ""}`}
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
                        <Button variant="outline" onClick={handleCloseDialog}>
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
