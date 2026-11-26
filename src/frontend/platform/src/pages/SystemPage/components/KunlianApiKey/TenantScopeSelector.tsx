import {
  Alert,
  Button,
  Checkbox,
  Input,
  Radio,
  RadioGroup,
  SearchInput,
  Tag,
} from "@bisheng/ui";
import { Outlined } from "bisheng-icons";
import {
  useMemo,
  useState,
  type ClipboardEvent,
  type KeyboardEvent,
} from "react";
import { useTranslation } from "react-i18next";
import { Label } from "@/components/bs-ui/label";
import type { KunlianDirectoryTenantItem } from "@/types/api/kunlianApiKey";
import { mergeUniqueTenants, parseTenantIdsInput } from "./utils";

export interface TenantScopeSelectorProps {
  availableTenants: KunlianDirectoryTenantItem[];
  loadingTenants: boolean;
  allTenants: boolean;
  onAllTenantsChange: (all: boolean) => void;
  selectedTenantIds: string[];
  onSelectedTenantIdsChange: (next: string[]) => void;
  tenantInput: string;
  onTenantInputChange: (next: string) => void;
  tenantError: string | null;
  onTenantErrorChange: (err: string | null) => void;
  onRefreshTenants: () => void;
  maxTenantCount: number;
}

const STATUS_TAG_COLOR: Record<string, "success" | "warning" | "default"> = {
  ACTIVE: "success",
  SUSPENDED: "warning",
};

export function TenantScopeSelector({
  availableTenants,
  loadingTenants,
  allTenants,
  onAllTenantsChange,
  selectedTenantIds,
  onSelectedTenantIdsChange,
  tenantInput,
  onTenantInputChange,
  tenantError,
  onTenantErrorChange,
  onRefreshTenants,
  maxTenantCount,
}: TenantScopeSelectorProps) {
  const { t } = useTranslation();
  const [tenantSearch, setTenantSearch] = useState("");

  const availableIdSet = useMemo(
    () => new Set(availableTenants.map((item) => item.external_tenant_id)),
    [availableTenants],
  );
  const selectedSet = useMemo(
    () => new Set(selectedTenantIds),
    [selectedTenantIds],
  );
  const customTenantIds = useMemo(
    () => selectedTenantIds.filter((id) => !availableIdSet.has(id)),
    [selectedTenantIds, availableIdSet],
  );

  const filteredTenants = useMemo(() => {
    const query = tenantSearch.trim().toLowerCase();
    if (!query) return availableTenants;
    return availableTenants.filter(
      (item) =>
        item.name.toLowerCase().includes(query) ||
        (item.code && item.code.toLowerCase().includes(query)) ||
        item.external_tenant_id.toLowerCase().includes(query),
    );
  }, [availableTenants, tenantSearch]);

  const activeTenants = useMemo(
    () => availableTenants.filter((item) => item.status === "ACTIVE"),
    [availableTenants],
  );
  const hasNonActiveTenants =
    activeTenants.length > 0 && activeTenants.length < availableTenants.length;

  const commitTenantTokens = (raw: string) => {
    const { valid, tooLong, hasWildcard } = parseTenantIdsInput(raw);
    if (hasWildcard) {
      onTenantErrorChange(t("kunlianApiKey.validation.wildcardUseModeToggle"));
      return;
    }
    if (tooLong.length > 0) {
      onTenantErrorChange(t("kunlianApiKey.validation.tenantTooLong"));
      return;
    }
    if (!valid.length) return;
    const merged = mergeUniqueTenants(selectedTenantIds, valid);
    if (merged.length > maxTenantCount) {
      onTenantErrorChange(
        t("kunlianApiKey.validation.tenantCountLimit", {
          max: maxTenantCount,
        }),
      );
      return;
    }
    onTenantErrorChange(null);
    onSelectedTenantIdsChange(merged);
    onTenantInputChange("");
  };

  const handleToggleTenant = (tenantId: string, checked: boolean) => {
    onTenantErrorChange(null);
    if (checked) {
      if (selectedSet.has(tenantId)) return;
      const merged = [...selectedTenantIds, tenantId];
      if (merged.length > maxTenantCount) {
        onTenantErrorChange(
          t("kunlianApiKey.validation.tenantCountLimit", {
            max: maxTenantCount,
          }),
        );
        return;
      }
      onSelectedTenantIdsChange(merged);
    } else {
      onSelectedTenantIdsChange(
        selectedTenantIds.filter((item) => item !== tenantId),
      );
    }
  };

  const handleSelectAllTenants = (onlyActive: boolean) => {
    onTenantErrorChange(null);
    const source = onlyActive ? activeTenants : availableTenants;
    const ids = source.map((item) => item.external_tenant_id);
    const merged = mergeUniqueTenants(selectedTenantIds, ids);
    if (merged.length > maxTenantCount) {
      onTenantErrorChange(
        t("kunlianApiKey.validation.tenantCountLimit", {
          max: maxTenantCount,
        }),
      );
      return;
    }
    onSelectedTenantIdsChange(merged);
  };

  const handleTenantInputKeyDown = (
    event: KeyboardEvent<HTMLInputElement>,
  ) => {
    if (event.key === "Enter" && !event.nativeEvent.isComposing) {
      event.preventDefault();
      commitTenantTokens(tenantInput);
    }
  };

  const handleTenantInputPaste = (event: ClipboardEvent<HTMLInputElement>) => {
    const text = event.clipboardData.getData("text");
    if (!text) return;
    const { valid, hasWildcard } = parseTenantIdsInput(text);
    if (hasWildcard || valid.length > 1 || /[\r\n,，;；]/.test(text)) {
      event.preventDefault();
      commitTenantTokens(text);
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <Label>{t("kunlianApiKey.fields.tenantScope")} *</Label>
        {!allTenants ? (
          <span className="text-xs text-muted-foreground">
            {t("kunlianApiKey.form.tenantCount", {
              count: selectedTenantIds.length,
              max: maxTenantCount,
            })}
          </span>
        ) : null}
      </div>

      <RadioGroup
        direction="vertical"
        value={allTenants ? "all" : "specific"}
        onValueChange={(value) => {
          onTenantErrorChange(null);
          onAllTenantsChange(value === "all");
        }}
      >
        <Radio
          value="specific"
          description={t("kunlianApiKey.scope.specificModeDesc")}
        >
          {t("kunlianApiKey.scope.specificModeLabel")}
        </Radio>
        <Radio
          value="all"
          description={t("kunlianApiKey.scope.allModeDesc")}
        >
          {t("kunlianApiKey.scope.allModeLabel")}
        </Radio>
      </RadioGroup>

      {allTenants ? (
        <Alert
          type="warning"
          title={t("kunlianApiKey.scope.allAlertTitle")}
          description={t("kunlianApiKey.scope.allAlertDesc")}
        />
      ) : (
        <div className="space-y-2.5 rounded-md border p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <SearchInput
              className="w-56 flex-1"
              size="small"
              value={tenantSearch}
              clearLabel={t("sharedUi.clear")}
              placeholder={t("kunlianApiKey.scope.searchTenantsPlaceholder")}
              onChange={(event) => setTenantSearch(event.target.value)}
            />
            <div className="flex flex-wrap items-center gap-1.5">
              {availableTenants.length > 0 ? (
                <Button
                  type="button"
                  size="small"
                  variant="link"
                  onClick={() => handleSelectAllTenants(false)}
                >
                  {t("kunlianApiKey.actions.selectAllTenants")}
                </Button>
              ) : null}
              {hasNonActiveTenants ? (
                <Button
                  type="button"
                  size="small"
                  variant="link"
                  onClick={() => handleSelectAllTenants(true)}
                >
                  {t("kunlianApiKey.actions.selectActiveTenants")}
                </Button>
              ) : null}
              {selectedTenantIds.length > 0 ? (
                <Button
                  type="button"
                  size="small"
                  variant="link"
                  onClick={() => {
                    onSelectedTenantIdsChange([]);
                    onTenantErrorChange(null);
                  }}
                >
                  {t("kunlianApiKey.actions.clearTenants")}
                </Button>
              ) : null}
              <Button
                type="button"
                size="small"
                variant="text"
                color="default"
                iconOnly
                disabled={loadingTenants}
                aria-label={t("kunlianApiKey.actions.refreshTenants")}
                onClick={onRefreshTenants}
              >
                <Outlined.Refresh
                  aria-hidden="true"
                  className={`size-3.5 ${loadingTenants ? "animate-spin" : ""}`}
                />
              </Button>
            </div>
          </div>

          {loadingTenants && availableTenants.length === 0 ? (
            <p className="py-4 text-center text-xs text-muted-foreground">
              {t("kunlianApiKey.scope.loadingTenants")}
            </p>
          ) : filteredTenants.length > 0 ? (
            <div className="max-h-48 divide-y overflow-y-auto rounded-md border">
              {filteredTenants.map((tenant) => {
                const checked = selectedSet.has(tenant.external_tenant_id);
                const statusKey =
                  tenant.status === "ACTIVE" || tenant.status === "SUSPENDED"
                    ? tenant.status
                    : "BOUND";
                return (
                  <label
                    key={tenant.external_tenant_id}
                    className="flex cursor-pointer items-start gap-2.5 px-3 py-2 hover:bg-muted/40"
                  >
                    <Checkbox
                      className="mt-0.5"
                      checked={checked}
                      onCheckedChange={(next) =>
                        handleToggleTenant(
                          tenant.external_tenant_id,
                          next === true,
                        )
                      }
                    />
                    <span className="min-w-0 flex-1 space-y-0.5">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-sm font-medium">
                          {tenant.name}
                        </span>
                        {tenant.code ? (
                          <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px] text-muted-foreground">
                            {tenant.code}
                          </code>
                        ) : null}
                        <Tag
                          size="small"
                          color={STATUS_TAG_COLOR[tenant.status] || "default"}
                        >
                          {t(`kunlianApiKey.tenantStatus.${statusKey}`)}
                        </Tag>
                        {tenant.local_tenant_id ? (
                          <span className="text-xs text-muted-foreground">
                            {t("kunlianApiKey.scope.boundLocalTenant", {
                              id: tenant.local_tenant_id,
                            })}
                          </span>
                        ) : null}
                      </span>
                      <span className="block truncate font-mono text-[11px] text-muted-foreground">
                        {tenant.external_tenant_id}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
          ) : (
            <p className="rounded-md border border-dashed py-3 text-center text-xs text-muted-foreground">
              {availableTenants.length === 0
                ? t("kunlianApiKey.scope.emptySyncedTenants")
                : t("kunlianApiKey.scope.noMatchingTenants")}
            </p>
          )}

          {customTenantIds.length > 0 ? (
            <div className="space-y-1">
              <p className="text-xs text-muted-foreground">
                {t("kunlianApiKey.scope.manualTagsLabel")}
              </p>
              <div className="flex max-h-24 flex-wrap gap-1.5 overflow-y-auto rounded-md border bg-muted/20 p-2">
                {customTenantIds.map((tenantId) => (
                  <Tag
                    key={tenantId}
                    size="small"
                    closable
                    closeLabel={t("kunlianApiKey.actions.removeTenant", {
                      tenantId,
                    })}
                    onClose={() =>
                      onSelectedTenantIdsChange(
                        selectedTenantIds.filter((item) => item !== tenantId),
                      )
                    }
                  >
                    {tenantId}
                  </Tag>
                ))}
              </div>
            </div>
          ) : null}

          <div className="space-y-1 pt-1">
            <div className="flex gap-2">
              <Input
                id="kl-tenant-input"
                size="small"
                value={tenantInput}
                status={tenantError ? "error" : "default"}
                placeholder={t("kunlianApiKey.form.tenantPlaceholder")}
                onChange={(event) => {
                  onTenantInputChange(event.target.value);
                  if (tenantError) onTenantErrorChange(null);
                }}
                onKeyDown={handleTenantInputKeyDown}
                onPaste={handleTenantInputPaste}
              />
              <Button
                type="button"
                size="small"
                variant="outlined"
                color="default"
                disabled={!tenantInput.trim()}
                onClick={() => commitTenantTokens(tenantInput)}
              >
                {t("kunlianApiKey.actions.addTenant")}
              </Button>
            </div>
            <p className="text-xs text-muted-foreground">
              {t("kunlianApiKey.form.tenantHint")}
            </p>
            {tenantError ? (
              <p className="text-xs text-destructive">{tenantError}</p>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}
