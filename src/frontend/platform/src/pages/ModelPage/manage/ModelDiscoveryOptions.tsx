import { useState } from "react";
import { Button, Input } from "@bisheng/ui";
import { Label } from "@/components/bs-ui/label";
import { Select } from "@bisheng/ui";
import { useSelectLabels } from "@/components/bs-comp/formFields/useSelectLabels";
import { DiscoverySource } from "@/controllers/API/modelDiscovery";
import { useTranslation } from "react-i18next";

export const presetProviders = new Set([
  "zhipu",
  "spark",
  "minimax",
  "tencent",
]);

interface ModelDiscoveryOptionsProps {
  provider: string;
  requiredReason: string;
  source: DiscoverySource;
  options: Record<string, string>;
  onChange: (source: DiscoverySource, options: Record<string, string>) => void;
}

type OptionField = {
  key: string;
  label: string;
  placeholder?: string;
  secret?: boolean;
};
const providerFields: Record<string, OptionField[]> = {
  qwen: [
    { key: "workspace_id", label: "discoveryWorkspace" },
    {
      key: "catalog_url",
      label: "discoveryCatalogUrl",
      placeholder:
        "https://<workspace>.cn-beijing.maas.aliyuncs.com/api/v1/models",
    },
  ],
  volcengine: [
    { key: "access_key_id", label: "discoveryAccessKey", secret: true },
    { key: "secret_access_key", label: "discoverySecretKey", secret: true },
    { key: "session_token", label: "discoverySessionToken", secret: true },
    { key: "project_name", label: "discoveryProject", placeholder: "default" },
  ],
  azure_openai: [
    {
      key: "resource_id",
      label: "discoveryResourceId",
      placeholder:
        "/subscriptions/.../resourceGroups/.../providers/Microsoft.CognitiveServices/accounts/...",
    },
    {
      key: "management_token",
      label: "discoveryManagementToken",
      secret: true,
    },
  ],
};

export function ModelDiscoveryOptions({
  provider,
  requiredReason,
  source,
  options,
  onChange,
}: ModelDiscoveryOptionsProps) {
  const { t } = useTranslation("model");
  const selectLabels = useSelectLabels();
  const [advanced, setAdvanced] = useState(false);
  const presets = presetProviders.has(provider);
  const needsFields = source === "auto" && !!requiredReason;
  const fields =
    source === "auto" && (advanced || needsFields)
      ? (providerFields[provider] || []).filter(
          (field) =>
            advanced ||
            (provider === "qwen"
              ? field.key === "workspace_id"
              : provider === "volcengine"
                ? ["access_key_id", "secret_access_key"].includes(field.key)
                : true),
        )
      : [];
  if (!presets && !providerFields[provider]) return null;
  return (
    <div className="space-y-3">
      <Button
        type="button"
        variant="text"
        color="default"
        size="small"
        aria-expanded={advanced}
        onClick={() => setAdvanced((value) => !value)}
      >
        {t("model.discoveryAdvancedSettings")}
      </Button>
      {advanced && (
        <div className="flex items-center gap-3">
          <Label htmlFor="discovery-source">{t("model.discoverySource")}</Label>
          <Select
            {...selectLabels}
            id="discovery-source"
            className="w-48"
            aria-label={t("model.discoverySource")}
            value={source}
            onChange={(value) => {
              if (value) onChange(value as DiscoverySource, {});
            }}
            options={[
              { value: "auto", label: t("model.discoverySourceAuto") },
              { value: "live", label: t("model.discoverySourceLive") },
              ...(presets
                ? [{ value: "preset", label: t("model.discoverySourcePreset") }]
                : []),
            ]}
          />
        </div>
      )}
      {fields.length > 0 && (
        <div className="rounded-md border p-3">
          <p className="text-sm font-medium">
            {t(`model.discoveryOptions_${provider}`)}
          </p>
          <p className="mt-2 text-xs text-muted-foreground">
            {t(`model.discoveryOptionsHint_${provider}`)}
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2">
            {fields.map((field) => (
              <div key={field.key} className="space-y-1">
                <Label htmlFor={`discovery-${field.key}`}>
                  {t(`model.${field.label}`)}
                </Label>
                <Input
                  id={`discovery-${field.key}`}
                  autoComplete="off"
                  type={field.secret ? "password" : "text"}
                  placeholder={field.placeholder}
                  value={options[field.key] || ""}
                  onChange={(event) =>
                    onChange(source, {
                      ...options,
                      [field.key]: event.target.value,
                    })
                  }
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
