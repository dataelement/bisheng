import { Input } from "@/components/bs-ui/input";
import { Label } from "@/components/bs-ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/bs-ui/select";
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
  source,
  options,
  onChange,
}: ModelDiscoveryOptionsProps) {
  const { t } = useTranslation("model");
  const presets = presetProviders.has(provider);
  const fields = source === "auto" ? providerFields[provider] || [] : [];
  if (!presets && !providerFields[provider]) return null;
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Label htmlFor="discovery-source">{t("model.discoverySource")}</Label>
        <Select
          value={source}
          onValueChange={(value) => onChange(value as DiscoverySource, {})}
        >
          <SelectTrigger
            id="discovery-source"
            className="w-48"
            aria-label={t("model.discoverySource")}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="auto">
              {t("model.discoverySourceAuto")}
            </SelectItem>
            <SelectItem value="live">
              {t("model.discoverySourceLive")}
            </SelectItem>
            {presets && (
              <SelectItem value="preset">
                {t("model.discoverySourcePreset")}
              </SelectItem>
            )}
          </SelectContent>
        </Select>
      </div>
      {fields.length > 0 && (
        <details open={provider === "volcengine" || provider === "qwen"}>
          <summary className="cursor-pointer text-sm text-muted-foreground">
            {t(`model.discoveryOptions_${provider}`)}
          </summary>
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
        </details>
      )}
    </div>
  );
}
