import modelDefaults from "../../../../../public/locales/zh-Hans/model.json";
import { useDshBrowserConfig } from "@/hooks/useDshBrowserConfig";
// @ts-strict-ignore
import { shouldRetryApiError } from "@bisheng/api-client";
import { Button, Cascader, toast } from "@bisheng/ui";
import { Outlined } from "bisheng-icons";

import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { Label } from "@/components/bs-ui/label";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import {
  fromModelCascaderValue,
  toModelCascaderOptions,
  toModelCascaderValue,
} from "@/components/bs-comp/formFields/modelOptions";

import { ModelFieldHint } from "../ModelFieldHint";
import { getLinsightModelEnvelope, updateLinsightModelConfig } from "@/controllers/API/finetune";
import { FallbackBlockedBanner, InheritedBadge } from "../SystemConfigBanners";
import { showApiError } from "@/controllers/request";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { useModel } from "..";
import { UserSelectableModels } from "../UserSelectableModels";
import { updateModelMetadata } from "../userModelMetadata";
import { hasValidWorkbenchEmbeddingModelId } from "./workbenchModelValidation";

export const ModelSelect = ({
  required = false,
  close = false,
  label,
  tooltipText = "",
  value,
  options,
  onChange,
  placeholder = "",
}) => {
  const { t } = useTranslation();
  const selectLabels = useSelectLabels();
  const cascaderOptions = useMemo(() => toModelCascaderOptions(options), [options]);
  const cascaderValue = useMemo(() => toModelCascaderValue(value, options), [options, value]);

  return (
    <div className="min-w-0">
      <Label className="bisheng-label">
        <span>{label}</span>
        {required && <span className="text-red-500 text-xs">*</span>}
        {tooltipText && <ModelFieldHint className="ml-1" content={tooltipText}></ModelFieldHint>}
      </Label>
      <Cascader
        {...selectLabels}
        className="w-full"
        options={cascaderOptions}
        value={cascaderValue}
        allowClear={close}
        onChange={(path) => onChange(fromModelCascaderValue(path))}
        placeholder={placeholder || t("build.selectModel")}
        aria-label={typeof label === "string" && label ? label : t("build.selectModel")}
        backLabel={t("sharedUi.back")}
        doneLabel={t("sharedUi.done")}
        searchPlaceholder={t("sharedUi.searchModels")}
      />
    </div>
  );
};

export default function WorkbenchModel({ data, onBack }) {
  const { config: enterpriseConfig } = useDshBrowserConfig();
  const { llmOptions, embeddings, asrModel, ttsModel } = useModel();
  const { t } = useTranslation("model");


  const [form, setForm] = useState<any>({
    sourceModelId: null,
    linsightDefaultModelId: null,
    chatDefaultModelId: null,
    asrModelId: null,
    ttsModelId: null,
    knowledgeSpaceLlmId: null,
    chatTitleLlmId: null,
    imageReadModelId: null,
    models: [],
  });

  const lastSaveFormDataRef = useRef(null);
  const [saveload, setSaveLoad] = useState(false);

  const { data: linsightConfig, isLoading: loading, refetch: refetchConfig, error } = useLinsightConfig();

  // Look up the model's own name from the cascader options by id, used as
  // the default displayName when the admin leaves it empty.
  const findModelLabel = (id) => {
    if (!id) return "";
    for (const group of llmOptions) {
      const hit = group.children?.find((el) => el.value == id);
      if (hit) return hit.label;
    }
    return "";
  };

  const submitConfig = async () => {
    const {
      linsightDefaultModelId,
      chatDefaultModelId,
      sourceModelId,
      asrModelId,
      ttsModelId,
      chatTitleLlmId,
      imageReadModelId,
      models,
    } = form;
    setSaveLoad(true);
    try {
      const data = {
        abstract_prompt: linsightConfig?.abstract_prompt,
        knowledge_space_llm: linsightConfig?.knowledge_space_llm,
        // Empty displayName falls back to the model's own name so the
        // workspace model picker never renders a blank option.
        models: models.map((m) => ({ ...m, displayName: m.displayName?.trim() || findModelLabel(m.id) })),
        embedding_model: { id: String(sourceModelId) },
        // Linsight default executor model: one of the workbench chat models' id.
        linsight_default_model_id: linsightDefaultModelId ? String(linsightDefaultModelId) : null,
        // Daily-mode default model: independent sibling of the Linsight default.
        chat_default_model_id: chatDefaultModelId ? String(chatDefaultModelId) : null,
        asr_model: asrModelId ? { id: String(asrModelId) } : null, // Accept an empty value.
        tts_model: ttsModelId ? { id: String(ttsModelId) } : null, // Accept an empty value.
        // Model used to generate app conversation titles.
        chat_title_llm: chatTitleLlmId ? { id: String(chatTitleLlmId) } : null, // Accept an empty value.
        image_read_model: imageReadModelId ? { id: String(imageReadModelId) } : null,
      };

      await updateLinsightModelConfig(data);
      lastSaveFormDataRef.current = { ...lastSaveFormDataRef.current, ...data };
      toast.show({ type: "success", message: String(t("model.saveSuccess") ?? "") });
      let updatedConfig;
      try {
        updatedConfig = await refetchConfig({ throwOnError: true });
      } catch (refreshError) {
        // The write committed. Keep the accepted form and report only the failed refresh.
        showApiError(refreshError);
        return;
      }

      // Apply refreshed data only when the refresh succeeds.
      const newConfig = updatedConfig.data;
      setForm({
        sourceModelId: newConfig?.embedding_model?.id || null,
        linsightDefaultModelId: newConfig?.linsight_default_model_id || null,
        chatDefaultModelId: newConfig?.chat_default_model_id || null,
        asrModelId: newConfig?.asr_model?.id || null,
        ttsModelId: newConfig?.tts_model?.id || null,
        chatTitleLlmId: newConfig?.chat_title_llm?.id || null,
        imageReadModelId: newConfig?.image_read_model?.id || null,
        knowledgeSpaceLlmId: newConfig?.knowledge_space_llm?.id || null,
        models: newConfig?.models || [],
      });

      lastSaveFormDataRef.current = {
        embedding_model: { id: newConfig?.embedding_model?.id },
        linsight_default_model_id: newConfig?.linsight_default_model_id || null,
        chat_default_model_id: newConfig?.chat_default_model_id || null,
        abstract_prompt: newConfig?.abstract_prompt || defalutPrompt,
        asr_model: { id: newConfig?.asr_model?.id },
        tts_model: { id: newConfig?.tts_model?.id },
        chat_title_llm: { id: newConfig?.chat_title_llm?.id },
        image_read_model: { id: newConfig?.image_read_model?.id },
        knowledge_space_llm: { id: newConfig?.knowledge_space_llm?.id },
        models: newConfig?.models || [],
      };
    } catch (err) {
      showApiError(err);
      throw err;
    } finally {
      setSaveLoad(false);
    }
  };

  // Check whether the embedding model changed.
  const checkEmbeddingModified = () => {
    const lastEmbeddingId = lastSaveFormDataRef.current?.embedding_model?.id;
    const currentEmbeddingId = form.sourceModelId;
    return lastEmbeddingId !== currentEmbeddingId;
  };

  const handleSave = () => {
    if (form.models.some((model) => String(model.description ?? "").length > 50)) return;
    const errors = [];
    if (!enterpriseConfig?.enabled && !form.models.length) {
      errors.push(t("model.chatModelRequired"));
    }
    // Reject blank rows: a model without an id serializes to `{ id: '' }`,
    // which reaches the client model picker as <SelectItem value="">
    // (empty string) and crashes the whole page in Radix. Force the admin
    // to pick a model or remove the empty row before saving.
    if (form.models.some((model) => !model.id)) {
      errors.push(t("model.chatModelRowRequired"));
    }
    if (!hasValidWorkbenchEmbeddingModelId(form.sourceModelId)) {
      errors.push(t("model.workVectorModel") + t("bs:required"));
    }
    if (errors.length) {
      toast.show({ type: "error", message: errors.filter(Boolean).join("\n") });
      return;
    }

    if (checkEmbeddingModified()) {
      bsConfirm({
        title: t("model.tip"),
        desc: t("model.confirmEmbeddingChange"),
        showClose: true,
        okTxt: t("model.confirm"),
        canelTxt: t("model.cancel"),
        onOk(next) {
          return submitConfig().then(next);
        },
        onCancel() {},
      });
    } else {
      void submitConfig().catch(showApiError);
    }
  };

  useEffect(() => {
    if (error) {
      return;
    }

    // Update the form and cache once the configuration is ready.
    if (linsightConfig) {
      setForm({
        sourceModelId: linsightConfig.embedding_model?.id || null,
        linsightDefaultModelId: linsightConfig.linsight_default_model_id || null,
        chatDefaultModelId: linsightConfig.chat_default_model_id || null,
        asrModelId: linsightConfig.asr_model?.id || null,
        ttsModelId: linsightConfig.tts_model?.id || null,
        chatTitleLlmId: linsightConfig.chat_title_llm?.id || null,
        imageReadModelId: linsightConfig.image_read_model?.id || null,
        knowledgeSpaceLlmId: linsightConfig.knowledge_space_llm?.id || null,
        models: linsightConfig.models || [],
      });

      lastSaveFormDataRef.current = {
        embedding_model: { id: linsightConfig.embedding_model?.id },
        linsight_default_model_id: linsightConfig.linsight_default_model_id || null,
        chat_default_model_id: linsightConfig.chat_default_model_id || null,
        abstract_prompt: linsightConfig.abstract_prompt || defalutPrompt,
        asr_model: { id: linsightConfig.asr_model?.id },
        tts_model: { id: linsightConfig.tts_model?.id },
        chat_title_llm: { id: linsightConfig.chat_title_llm?.id },
        image_read_model: { id: linsightConfig.image_read_model?.id },
        knowledge_space_llm: { id: linsightConfig.knowledge_space_llm?.id },
        models: linsightConfig.models || [],
      };
    }
  }, [linsightConfig, error, defalutPrompt, t]);

  if (loading)
    return (
      <div className="absolute w-full h-full top-0 left-0 flex justify-center items-center z-10 bg-[rgba(255,255,255,0.6)] dark:bg-blur-shared">
        <Outlined.Loading className="size-4 animate-spin" />
      </div>
    );
  const inheritedFromRoot = !!linsightConfig?.inherited_from_root;
  const fallbackBlocked = !!linsightConfig?.fallback_blocked;
  return (
    <div className="w-full max-w-[1440px] mx-auto gap-y-4 flex flex-col mt-8 relative">
      <FallbackBlockedBanner visible={fallbackBlocked} />
      {inheritedFromRoot && (
        <div className="-mb-2 text-xs text-muted-foreground flex items-center">
          <InheritedBadge visible={true} />
        </div>
      )}
      <UserSelectableModels
        data={data}
        configuredModels={form.models}
        enterpriseEnabled={!!enterpriseConfig?.enabled}
        disabled={saveload || !linsightConfig}
        onMetadataChange={(model, changes) =>
          setForm((prev) => ({
            ...prev,
            models: updateModelMetadata(prev.models, model, changes),
          }))
        }
      />
      <details className="mt-2 border-t pt-4">
        <summary className="cursor-pointer text-sm text-muted-foreground">
          {t("model.otherModelSettings")}
        </summary>
        <div className="mt-4 max-w-[880px] space-y-4">
          <ModelSelect
            close
            label={t("model.workVectorModel")}
            tooltipText={t("model.workVectorModelTooltip")}
            value={form.sourceModelId}
            options={embeddings}
            onChange={(val) => setForm({ ...form, sourceModelId: val })}
            required
          />
          <h3 className="bisheng-label">{t("model.workbenchVoiceModel")}</h3>
          <div className="border rounded-lg p-4 -mt-3 space-y-4">
            <ModelSelect
              close
              label={t("model.asrModel")}
              tooltipText={t("model.asrModelTooltip")}
              value={form.asrModelId}
              options={asrModel}
              onChange={(val) => setForm({ ...form, asrModelId: val })}
            />
            <ModelSelect
              close
              label={t("model.ttsModel")}
              tooltipText={t("model.ttsModelTooltip")}
              value={form.ttsModelId}
              options={ttsModel}
              onChange={(val) => setForm({ ...form, ttsModelId: val })}
            />
          </div>
          <ModelSelect
            close
            label={t("model.sessionTitleGenerationModel")}
            value={form.chatTitleLlmId}
            options={llmOptions}
            onChange={(val) => setForm({ ...form, chatTitleLlmId: val })}
          />
        </div>
      </details>
      <div className="mt-6 flex justify-end gap-4">
        <Button variant="outlined" color="default" onClick={onBack}>
          {t("model.cancel")}
        </Button>
        <Button disabled={saveload || !linsightConfig} onClick={handleSave}>
          {saveload && <Outlined.Loading className="mr-2 animate-spin" />}
          {t("model.save")}
        </Button>
      </div>
    </div>
  );
}

export function useLinsightConfig() {
  return useQuery({
    queryKey: ["linsightModelEnvelope"],
    queryFn: () => getLinsightModelEnvelope({ showError: false }),
    onError: showApiError,
    select: (env) => {
      // F022: backend returns {data, inherited_from_root, fallback_blocked}.
      // Hand the destructured shape back so the component can render the
      // Badge / Banner without re-fetching.
      const cfg = env?.data || {
        models: [],
        embedding_model: null,
        abstract_prompt: defalutPrompt,
        linsight_default_model_id: null,
        chat_default_model_id: null,
        asr_model: null,
        tts_model: null,
        knowledge_space_llm: null,
        chat_title_llm: null,
        image_read_model: null,
      };
      return {
        ...cfg,
        inherited_from_root: !!env?.inherited_from_root,
        fallback_blocked: !!env?.fallback_blocked,
      };
    },
    retry: (failureCount, error) => shouldRetryApiError(error) && failureCount < 1,
  });
}

// Keep the persisted default prompt in its original language, independent of the admin UI locale.
export const defalutPrompt = modelDefaults.model.defaultSummaryPrompt;
