import { Button, Switch, Tag } from "@bisheng/ui";
import { useTranslation } from "react-i18next";
import type { KunlianAutoOnboardingSetting } from "./kunlianConfigYaml";

interface KunlianAutoOnboardingCardProps {
  yamlOverride: KunlianAutoOnboardingSetting;
  deploymentDefault: boolean;
  loaded: boolean;
  saving: boolean;
  onToggle: (nextEnabled: boolean) => void;
  onResetInherit: () => void;
}

export function KunlianAutoOnboardingCard({
  yamlOverride,
  deploymentDefault,
  loaded,
  saving,
  onToggle,
  onResetInherit,
}: KunlianAutoOnboardingCardProps) {
  const { t } = useTranslation();

  const isOverridden = yamlOverride !== "inherit";
  const effectiveEnabled = isOverridden ? yamlOverride : deploymentDefault;
  const deploymentValueLabel = deploymentDefault
    ? t("system.kunlianAutoOnboarding.stateOn")
    : t("system.kunlianAutoOnboarding.stateOff");

  return (
    <div className="mb-3 shrink-0 rounded-lg border border-border bg-card px-4 py-3">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-1.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-text-1">
              {t("system.kunlianAutoOnboarding.title")}
            </span>
            <Tag size="small" color={isOverridden ? "brand" : "default"}>
              {isOverridden
                ? t("system.kunlianAutoOnboarding.sourceOverride")
                : t("system.kunlianAutoOnboarding.sourceInherit", { value: deploymentValueLabel })}
            </Tag>
            <Tag size="small" dot color={effectiveEnabled ? "success" : "default"}>
              {effectiveEnabled
                ? t("system.kunlianAutoOnboarding.stateOn")
                : t("system.kunlianAutoOnboarding.stateOff")}
            </Tag>
          </div>
          <p className="text-xs leading-relaxed text-text-3">
            {t("system.kunlianAutoOnboarding.desc")}
          </p>
          <p className="text-xs leading-relaxed text-text-4">
            {t("system.kunlianAutoOnboarding.scopeHint")}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-3 pt-0.5">
          {isOverridden && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              disabled={!loaded || saving}
              onClick={onResetInherit}
            >
              {t("system.kunlianAutoOnboarding.resetInherit")}
            </Button>
          )}
          <Switch
            aria-label={t("system.kunlianAutoOnboarding.title")}
            checked={effectiveEnabled}
            disabled={!loaded}
            loading={saving}
            onCheckedChange={onToggle}
          />
        </div>
      </div>
    </div>
  );
}
