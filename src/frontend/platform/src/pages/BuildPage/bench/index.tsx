// @ts-strict-ignore
import { notification } from "@bisheng/ui";
// src/features/chat-config/ChatConfig.tsx
import { bsConfirm } from "@/components/bs-ui/alertDialog/useConfirm";

import { generateUUID } from "@/components/bs-ui/utils";
import { locationContext } from "@/contexts/locationContext";
import {
  getDailyConfigApi,
  getLinsiConfigApi,
  setDailyConfigApi,
  setLinsiConfigApi,
} from "@/controllers/API";
import { getToolsApi } from "@/controllers/API/tools";
import { showApiError } from "@/controllers/request";
import { useContext, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { resolveConfigEnvelope } from "./ConfigInheritanceBanner";
import { clampMenuName, toStoredMenuName } from "./menuDisplayName";
import { Model } from "./ModelManagement";
import { OrgKbConfig as OrgKbConfigType } from "./OrgKbConfig";
import { ToolConfig as ToolConfigType } from "./ToolsConfig";

export interface FormErrors {
  homeMenuDisplayName: string;
  welcomeMessage: string;
  functionDescription: string;
  tabDisplayName: string;
  taskModeName: string;
  inputPlaceholder: string;
  modelNames: string[] | string[][];
  systemPrompt: string;
  model: string;
  kownledgeBase: string;
  applicationCenterWelcomeMessage: string;
  applicationCenterDescription: string;
}

export interface ChatConfigForm {
  menuShow: boolean;

  homeMenuDisplayName: string;

  appCenterMenuDisplayName: string;
  systemPrompt: string;
  sidebarIcon: {
    enabled: boolean;
    image: string;
    relative_path: string;
  };
  assistantIcon: {
    enabled: boolean;
    image: string;
    relative_path: string;
  };
  welcomeMessage: string;
  functionDescription: string;
  inputPlaceholder: string;
  applicationCenterWelcomeMessage: string;
  applicationCenterDescription: string;
  models: Model[];
  maxTokens: number;
  voiceInput: {
    enabled: boolean;
    model: string;
  };
  knowledgeBase: {
    enabled: boolean;
    prompt: string;
  };
  fileUpload: {
    enabled: boolean;
    prompt: string;
  };

  skillEntry: {
    enabled: boolean;
  };
  recommendedApps: string[];

  tabDisplayName?: string;
  // v2.5 Agent-mode additions
  tools: ToolConfigType[];
  orgKbs: OrgKbConfigType[];

  linsightConfig: {
    linsight_entry: boolean;
    input_placeholder: string;
    tools: unknown[];
    tab_display_name: string;
  };
}
export { DailyChatConfig as default } from "./DailyChatConfig";

interface UseChatConfigProps {
  homeMenuDisplayNameRef: React.RefObject<HTMLDivElement>;
  welcomeMessageRef: React.RefObject<HTMLDivElement>;
  functionDescriptionRef: React.RefObject<HTMLDivElement>;
  inputPlaceholderRef: React.RefObject<HTMLDivElement>;
  taskModeNameRef: React.RefObject<HTMLDivElement>;
  knowledgeBaseRef: React.RefObject<HTMLDivElement>;
  modelRefs: React.MutableRefObject<(HTMLDivElement | null)[]>;
  systemPromptRef: React.RefObject<HTMLDivElement>;
  modelManagementContainerRef: React.RefObject<HTMLDivElement>; // New
}

export const useChatConfig = (
  refs: UseChatConfigProps,
  scopeVersion: number,
  onBeforePersist?: () => Promise<boolean>,
) => {
  const { t } = useTranslation();

  const [formData, setFormData] = useState<ChatConfigForm>({
    // menuShow: true,
    // Fresh-deployment default — overwritten by API value when present.
    systemPrompt: t("chatConfig.systemPrompt2"),
    // Blank until configured — the input placeholder shows the default name
    homeMenuDisplayName: "",
    appCenterMenuDisplayName: "",
    sidebarIcon: { enabled: true, image: "", relative_path: "" },
    assistantIcon: { enabled: true, image: "", relative_path: "" },
    welcomeMessage: "",
    functionDescription: "",
    inputPlaceholder: "",
    applicationCenterWelcomeMessage: "",
    applicationCenterDescription: "",
    models: [{ key: generateUUID(4), id: null, name: "", displayName: "", visual: false }],
    maxTokens: 15000,
    voiceInput: { enabled: false, model: "" },
    knowledgeBase: {
      enabled: true,
      prompt: t("chatConfig.internationalization"),
    },
    fileUpload: {
      enabled: true,
      prompt: `{file_content}
{question}`,
    },
    // F035 (v2.6): Add-Skill entry defaults off until admin opts in.
    skillEntry: {
      enabled: false,
    },

    tabDisplayName: t("dailyFullName"),
    tools: [],
    orgKbs: [],
    recommendedApps: [],
    linsightConfig: {
      linsight_entry: true,
      input_placeholder: "",
      tools: [],
      tab_display_name: t("chatConfig.taskModeFullName"),
    },
  });

  // Simple deep comparison to avoid circular refresh caused by parent-child mutual setting
  const isDeepEqual = (a: any, b: any) => {
    try {
      return JSON.stringify(a) === JSON.stringify(b);
    } catch {
      return a === b;
    }
  };

  useEffect(() => {
    // Preset-tool list is fetched alongside config so fresh deployments can

    // is authoritative (t_gpts_tools* tables), so tool_key is looked up at
    // runtime rather than hardcoded.
    setConfigMeta(null);
    Promise.all([getDailyConfigApi(), getToolsApi("default"), getLinsiConfigApi()])
      .then(([res, toolsRes, linsightRes]) => {
        const { data: cfg, meta } = resolveConfigEnvelope<any>(res);
        setConfigMeta(meta);
        const linsightCfg = linsightRes ? resolveConfigEnvelope<any>(linsightRes).data || {} : {};
        setFormData((prev) => ({
          ...prev,
          linsightConfig: {
            linsight_entry: linsightCfg.linsight_entry ?? prev.linsightConfig.linsight_entry,
            input_placeholder: linsightCfg.input_placeholder ?? prev.linsightConfig.input_placeholder,
            tools: Array.isArray(linsightCfg.tools) ? linsightCfg.tools : prev.linsightConfig.tools,
            tab_display_name:
              typeof linsightCfg.tab_display_name === "string" && linsightCfg.tab_display_name.trim()
                ? linsightCfg.tab_display_name.trim()
                : prev.linsightConfig.tab_display_name,
          },
        }));
        const presetTools: any[] = Array.isArray(toolsRes) ? toolsRes : [];

        const buildDefaultTools = (): ToolConfigType[] => {
          for (const parent of presetTools) {
            const child = (parent.children || []).find((c: any) => c.tool_key === "web_search");
            if (child) {
              return [
                {
                  id: parent.id,
                  name: parent.name,
                  is_preset: parent.is_preset,
                  description: parent.description,
                  default_checked: true,
                  children: [
                    {
                      id: child.id,
                      name: child.name,
                      tool_key: child.tool_key,
                      desc: child.desc,
                    },
                  ],
                },
              ];
            }
          }
          return [];
        };

        setFormData((prev) => {
          const mergeObj = (a: any, b: any) => (b != null && typeof b === "object" ? { ...a, ...b } : a);

          // Fresh deployment: no WORKSTATION config row yet. Seed both
          // systemPrompt and web_search from defaults; leave other fields
          // at their initial-state values.
          if (!cfg) {
            return {
              ...prev,
              systemPrompt: t("chatConfig.systemPrompt2"),
              tools: buildDefaultTools(),
            };
          }

          // Legacy upgrade path: missing `tools` field → seed web_search.
          // Explicit [] (admin cleared) is preserved.
          const toolsFromCfg: ToolConfigType[] = Array.isArray(cfg.tools)
            ? cfg.tools
            : cfg.tools === undefined
              ? buildDefaultTools()
              : prev.tools;

          // Treat empty string as "not configured" so the default prompt
          // fills in instead of an empty textarea.
          const cfgSystemPrompt =
            typeof cfg.systemPrompt === "string" && cfg.systemPrompt.trim()
              ? cfg.systemPrompt
              : t("chatConfig.systemPrompt2");

          return {
            ...prev,
            // Blank = unconfigured; the placeholder shows the default and the client localizes it
            homeMenuDisplayName:
              typeof cfg.homeMenuDisplayName === "string" ? cfg.homeMenuDisplayName.trim() : "",
            appCenterMenuDisplayName: cfg.appCenterMenuDisplayName ?? prev.appCenterMenuDisplayName,
            welcomeMessage: cfg.welcomeMessage ?? prev.welcomeMessage,
            functionDescription: cfg.functionDescription ?? prev.functionDescription,
            inputPlaceholder: cfg.inputPlaceholder ?? prev.inputPlaceholder,
            applicationCenterWelcomeMessage:
              cfg.applicationCenterWelcomeMessage ?? prev.applicationCenterWelcomeMessage,
            applicationCenterDescription:
              cfg.applicationCenterDescription ?? prev.applicationCenterDescription,
            maxTokens: typeof cfg.maxTokens === "number" ? cfg.maxTokens : prev.maxTokens,
            systemPrompt: cfgSystemPrompt,
            sidebarIcon: mergeObj(prev.sidebarIcon, cfg.sidebarIcon),
            assistantIcon: mergeObj(prev.assistantIcon, cfg.assistantIcon),
            knowledgeBase: mergeObj(prev.knowledgeBase, cfg.knowledgeBase),
            fileUpload: mergeObj(prev.fileUpload, cfg.fileUpload),
            // Absent skillEntry (legacy configs) keeps the default-off state.
            skillEntry: mergeObj(prev.skillEntry, cfg.skillEntry),
            tabDisplayName: (() => {
              // Treat empty string / whitespace as "API empty" and don't override defaults.
              const raw = (cfg as any).tabDisplayName ?? (cfg as any).tab_display_name;
              if (typeof raw !== "string") return prev.tabDisplayName;
              const trimmed = raw.trim();
              return trimmed ? trimmed : prev.tabDisplayName;
            })(),
            tools: toolsFromCfg,
            orgKbs: Array.isArray(cfg.orgKbs) ? cfg.orgKbs : prev.orgKbs,
            recommendedApps: Array.isArray(cfg.recommendedApps) ? cfg.recommendedApps : prev.recommendedApps,
          };
        });
      })
      .catch(showApiError);
  }, [scopeVersion, t]);

  const [errors, setErrors] = useState<FormErrors>({
    homeMenuDisplayName: "",
    welcomeMessage: "",
    functionDescription: "",
    tabDisplayName: "",
    taskModeName: "",
    inputPlaceholder: "",
    kownledgeBase: "",
    model: "",
    modelNames: [],
    systemPrompt: "",
    applicationCenterWelcomeMessage: "",
    applicationCenterDescription: "",
  });
  const [configMeta, setConfigMeta] = useState<any>(null);

  const handleInputChange = (field: keyof ChatConfigForm, value: string, maxLength: number) => {
    if (field === "maxTokens" && value !== "" && (!Number.isFinite(Number(value)) || Number(value) < 0))
      return;
    setFormData((prev) => ({ ...prev, [field]: value }));

    if (value.length >= maxLength) {
      setErrors((prev) => ({ ...prev, [field]: t("chatConfig.errors.maxCharacters", { count: maxLength }) }));
    } else {
      setErrors((prev) => ({ ...prev, [field]: "" }));
    }
  };

  // Menu name: truncate past the display-width cap; blank is allowed (client localizes it)
  const handleMenuNameChange = (field: "homeMenuDisplayName", value: string) => {
    setFormData((prev) => ({ ...prev, [field]: clampMenuName(value) }));
    setErrors((prev) => ({ ...prev, [field]: "" }));
  };

  // F035: edits to the merged task-mode fields (legacy linsight config).
  const handleLinsightChange = (field: "tab_display_name" | "input_placeholder", value: string) => {
    setFormData((prev) => ({
      ...prev,
      linsightConfig: { ...prev.linsightConfig, [field]: value },
    }));
    if (field === "tab_display_name") {
      setErrors((prev) => ({ ...prev, taskModeName: "" }));
    }
  };

  const toggleFeature = (feature: keyof ChatConfigForm, enabled: boolean) => {
    setFormData((prev) => ({
      ...prev,
      [feature]: { ...prev[feature], enabled },
    }));
  };

  const validateForm = (): {
    isValid: boolean;
    firstErrorRef: React.RefObject<HTMLDivElement> | null;
    modelErrorMessages: string[];
  } => {
    let isValid = true;
    let firstErrorRef: React.RefObject<HTMLDivElement> | null = null;
    const modelErrorMessages: string[] = [];
    if (!Number.isFinite(Number(formData.maxTokens)) || Number(formData.maxTokens) < 0) {
      isValid = false;
      modelErrorMessages.push(t("sharedUi.minimum", { min: 0 }));
      if (!firstErrorRef) firstErrorRef = refs.modelManagementContainerRef;
    }
    const newErrors: FormErrors = {
      homeMenuDisplayName: "",
      welcomeMessage: "",
      functionDescription: "",
      tabDisplayName: "",
      taskModeName: "",
      inputPlaceholder: "",
      kownledgeBase: "",
      model: "",
      modelNames: [],
      applicationCenterWelcomeMessage: "",
      applicationCenterDescription: "",
      systemPrompt: "",
    };

    // round-trips through dataToSave) — no validation for it anymore.

    const taskModeName = (formData.linsightConfig.tab_display_name || "").trim();
    if (!taskModeName) {
      newErrors.taskModeName = t("chatConfig.errors.taskModeNameRequired");
      if (!firstErrorRef) firstErrorRef = refs.taskModeNameRef;
      isValid = false;
    } else if (taskModeName.length > 20) {
      newErrors.taskModeName = t("chatConfig.errors.maxCharacters", { count: 20 });
      if (!firstErrorRef) firstErrorRef = refs.taskModeNameRef;
      isValid = false;
    }

    // Validate welcome message
    if (formData.welcomeMessage.length > 1000) {
      newErrors.welcomeMessage = t("chatConfig.errors.maxCharacters", { count: 1000 });
      if (!firstErrorRef) firstErrorRef = refs.welcomeMessageRef;
      isValid = false;
    }

    // Validate function description
    if (formData.functionDescription.length > 1000) {
      newErrors.functionDescription = t("chatConfig.errors.maxCharacters", { count: 1000 });
      if (!firstErrorRef) firstErrorRef = refs.functionDescriptionRef;
      isValid = false;
    }

    // Validate input placeholder
    if (formData.inputPlaceholder.length > 1000) {
      newErrors.inputPlaceholder = t("chatConfig.errors.maxCharacters", { count: 1000 });
      if (!firstErrorRef) firstErrorRef = refs.inputPlaceholderRef;
      isValid = false;
    }

    if (formData.knowledgeBase.prompt.length > 30000) {
      newErrors.kownledgeBase = t("chatConfig.errors.maxCharacters", { count: 30000 });
      if (!firstErrorRef) firstErrorRef = refs.knowledgeBaseRef;
      isValid = false;
    }

    if (formData.systemPrompt?.length > 30000) {
      newErrors.systemPrompt = t("chatConfig.errors.maxCharacters", { count: 30000 });
      if (!firstErrorRef) firstErrorRef = refs.systemPromptRef;
      isValid = false;
    }

    newErrors.modelNames = [];
    setErrors(newErrors);

    return {
      isValid,
      firstErrorRef,
      modelErrorMessages: Array.from(new Set(modelErrorMessages)),
    };
  };

  const { reloadConfig } = useContext(locationContext);

  /**
   * Guard against persisting a form that never received the saved config.
   *
   * This form round-trips whatever the GET handed it, so two states are
   * destructive to save blindly: `is_fallback` (backend served its built-in
   * defaults because nothing resolved) and a null meta (the GET never
   * resolved, leaving the form on its initial defaults). Both look exactly
   * like a deliberate "reset everything" once written back — on 2026-08-13
   * that silently replaced a live workstation config, tools and all.
   */
  const confirmBlindOverwrite = () =>
    new Promise<boolean>((resolve) => {
      bsConfirm({
        title: t("chatConfig.blindOverwriteTitle"),
        desc: t("chatConfig.blindOverwriteDesc"),
        okTxt: t("chatConfig.blindOverwriteOk"),
        canelTxt: t("cancel", { ns: "bs" }),
        onOk(next) {
          resolve(true);
          next();
        },
        // Fires on every close path (cancel button, X, overlay); the
        // promise already settled when Ok was taken, so this is a no-op
        // there and the cancel answer everywhere else.
        onClose() {
          resolve(false);
        },
      });
    });

  const handleSave = async () => {
    const { isValid, firstErrorRef, modelErrorMessages } = validateForm();
    if (!isValid) {
      if (modelErrorMessages.length > 0) {
        notification.open({ type: "error", description: String(modelErrorMessages.join("; ") ?? "") });
      }
      if (firstErrorRef?.current) {
        firstErrorRef.current.scrollIntoView({
          behavior: "smooth",
          block: "center",
          inline: "nearest",
        });

        setTimeout(() => {
          const input = firstErrorRef.current?.querySelector('input, textarea, [role="combobox"]');
          if (input) input.focus();
        }, 300);
      }
      return false;
    }

    if (!configMeta || configMeta.is_fallback) {
      const proceed = await confirmBlindOverwrite();
      if (!proceed) return false;
    }

    if (onBeforePersist) {
      const ok = await onBeforePersist();
      if (!ok) return false;
    }

    const dataToSave = {
      // Blank stays blank: the client falls back to its localized menu name.
      homeMenuDisplayName: await toStoredMenuName(formData.homeMenuDisplayName, "bench.home"),
      appCenterMenuDisplayName: await toStoredMenuName(formData.appCenterMenuDisplayName, "bench.appCenter"),
      sidebarIcon: formData.sidebarIcon,
      assistantIcon: formData.assistantIcon,
      welcomeMessage: formData.welcomeMessage.trim(),
      functionDescription: formData.functionDescription.trim(),
      inputPlaceholder: formData.inputPlaceholder.trim(),
      applicationCenterWelcomeMessage:
        formData.applicationCenterWelcomeMessage.trim() || t("chatConfig.appCenterWelcomePlaceholder"),
      applicationCenterDescription:
        formData.applicationCenterDescription.trim() || t("chatConfig.appCenterDescriptionPlaceholder"),
      maxTokens: formData.maxTokens || 15000,
      systemPrompt: formData.systemPrompt,
      knowledgeBase: formData.knowledgeBase,
      fileUpload: formData.fileUpload,
      skillEntry: formData.skillEntry,
      tabDisplayName: formData.tabDisplayName ?? "",
      // v2.5 Agent-mode fields
      tools: formData.tools,
      orgKbs: formData.orgKbs,
      recommendedApps: formData.recommendedApps || [],
    };

    // F035: the merged task-mode fields persist to the legacy linsight
    // config endpoint; linsight_entry / tools round-trip untouched (the
    // entry toggle moved to role menus, tools share the daily pool).
    const linsightToSave = {
      linsight_entry: formData.linsightConfig.linsight_entry ?? true,
      input_placeholder: formData.linsightConfig.input_placeholder?.trim() || "",
      tools: formData.linsightConfig.tools || [],
      tab_display_name: (formData.linsightConfig.tab_display_name || "").trim(),
    };

    await Promise.all([setDailyConfigApi(dataToSave), setLinsiConfigApi(linsightToSave)]).then((res) => {
      if (res) {
        setConfigMeta({
          inherited_from_root: false,
          has_override: true,
        });
        notification.open({ type: "success", description: String(t("chatConfig.saveSuccess") ?? "") });
        reloadConfig();
      }
    });

    return true;
  };

  return {
    formData,
    errors,
    setFormData,
    setErrors,
    configMeta,
    handleInputChange,
    handleMenuNameChange,
    handleLinsightChange,
    toggleFeature,
    handleSave,
  };
};
